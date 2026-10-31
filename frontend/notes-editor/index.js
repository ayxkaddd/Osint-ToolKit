// Markdown note editor with Obsidian-style live preview, built on CodeMirror 6.
// Bundled into static/vendor/notes-editor.js by `npm run build:notes` and used
// through window.NotesEditor.create(parent, options) - see static/js/notes.js.
//
// Live preview: the markdown is parsed as you type; formatting is shown rendered
// and its syntax (#, **, [](), > ...) is hidden except where the cursor is, so the
// text under the cursor can be edited as plain markdown. The note stays plain markdown.
//
// References (Obsidian wikilink syntax):
//   [[result:<result_id>|label]]    link to a result in the investigation
//   [[email:alex@example.com]]      an identifier (any entity type) - pivot menu
//   ![[snapshot:<id>|label]]        a copy of a result attached to the note
// Typing [[ (or ![[ to attach) opens a search of results and identifiers.

import { EditorSelection, EditorState, StateField } from '@codemirror/state';
import { Decoration, EditorView, WidgetType, drawSelection, keymap, placeholder, tooltips } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { markdownKeymap, markdownLanguage } from '@codemirror/lang-markdown';
import { HighlightStyle, ensureSyntaxTree, syntaxHighlighting, syntaxTree } from '@codemirror/language';
import { autocompletion, completionKeymap } from '@codemirror/autocomplete';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import { tags } from '@lezer/highlight';

const WIKI = /(!?)\[\[([a-z_]+):([^\]|\n]+)(?:\|([^\]\n]*))?\]\]/g;
const MARKED = { Emphasis: 'cm-md-em', StrongEmphasis: 'cm-md-strong', Strikethrough: 'cm-md-strike', InlineCode: 'cm-md-code' };
const MARK_CHILD = { Emphasis: 'EmphasisMark', StrongEmphasis: 'EmphasisMark', Strikethrough: 'StrikethroughMark', InlineCode: 'CodeMark' };
const INLINE = new Set(['Link', 'Image', 'Emphasis', 'StrongEmphasis', 'InlineCode', 'Strikethrough', 'URL', 'Autolink', 'LinkMark', 'EmphasisMark']);

// ---------------------------------------------------------------------------
// Widgets
// ---------------------------------------------------------------------------

class BulletWidget extends WidgetType {
    eq() { return true; }
    toDOM() {
        const span = document.createElement('span');
        span.className = 'cm-md-bullet';
        span.textContent = '•';
        return span;
    }
}

class HrWidget extends WidgetType {
    eq() { return true; }
    toDOM() {
        const span = document.createElement('span');
        span.className = 'cm-md-hr';
        return span;
    }
}

class CheckboxWidget extends WidgetType {
    constructor(checked) { super(); this.checked = checked; }
    eq(other) { return other.checked === this.checked; }
    toDOM(view) {
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.className = 'cm-md-checkbox';
        box.checked = this.checked;
        box.addEventListener('mousedown', (event) => {
            event.preventDefault();
            const pos = view.posAtDOM(box);
            view.dispatch({ changes: { from: pos + 1, to: pos + 2, insert: this.checked ? ' ' : 'x' } });
        });
        return box;
    }
    ignoreEvent() { return true; }
}

// Images added to a note are stored by the toolkit and linked by a path on this server
const NOTE_IMAGE_URL = /^\/api\/investigations\/[0-9a-f-]+\/note-images\/[0-9a-f]{32}\.webp$/;

class ImageWidget extends WidgetType {
    constructor(src, alt) { super(); this.src = src; this.alt = alt; }
    eq(other) { return other.src === this.src && other.alt === this.alt; }
    toDOM() {
        const img = document.createElement('img');
        img.className = 'cm-md-image';
        img.src = this.src;
        img.alt = this.alt;
        img.loading = 'lazy';
        img.referrerPolicy = 'no-referrer';
        return img;
    }
}

class TableWidget extends WidgetType {
    constructor(source, host) { super(); this.source = source; this.host = host; }
    eq(other) { return other.source === this.source; }
    toDOM() {
        const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(c => c.trim());
        const lines = this.source.split('\n');
        const wrap = document.createElement('div');
        wrap.className = 'cm-md-table';
        const table = document.createElement('table');
        lines.forEach((line, i) => {
            if (i === 1) return; // the |---|---| delimiter row
            const tr = table.insertRow();
            for (const text of cells(line)) {
                const cell = document.createElement(i === 0 ? 'th' : 'td');
                cell.innerHTML = this.host.renderInline(text);
                tr.appendChild(cell);
            }
        });
        wrap.appendChild(table);
        return wrap;
    }
}

class ChipWidget extends WidgetType {
    constructor(link, host) { super(); this.link = link; this.host = host; }
    eq(other) { return ['embed', 'kind', 'value', 'label'].every(k => other.link[k] === this.link[k]); }
    toDOM() { return this.host.renderChip(this.link); }
    ignoreEvent() { return true; }
}

class EmbedWidget extends WidgetType {
    constructor(link, host) { super(); this.link = link; this.host = host; }
    eq(other) { return other.link.value === this.link.value && other.link.label === this.link.label; }
    toDOM(view) {
        const el = document.createElement('div');
        el.className = 'cm-md-embed';
        // "Edit" in the embed header shows the ![[...]] source
        el.addEventListener('click', (event) => {
            if (!event.target.closest('[data-embed-edit]')) return;
            const pos = view.posAtDOM(el);
            view.dispatch({ selection: EditorSelection.cursor(pos) });
            view.focus();
        });
        this.host.renderEmbed(this.link, el);
        return el;
    }
    ignoreEvent() { return true; }
}

// ---------------------------------------------------------------------------
// Live preview decorations
// ---------------------------------------------------------------------------

function buildDecorations(state, host) {
    const { doc, selection } = state;
    const decos = [];
    const touches = (from, to) => selection.ranges.some(r => r.from <= to && r.to >= from);
    const activeLines = new Set();
    for (const r of selection.ranges) {
        for (let n = doc.lineAt(r.from).number; n <= doc.lineAt(r.to).number; n++) activeLines.add(n);
    }
    const lineActive = pos => activeLines.has(doc.lineAt(pos).number);
    const hide = (from, to) => { if (from < to) decos.push(Decoration.replace({}).range(from, to)); };
    const lineClass = (pos, cls) => decos.push(Decoration.line({ class: cls }).range(doc.lineAt(pos).from));
    const eachLine = (from, to, fn) => {
        for (let n = doc.lineAt(from).number, last = doc.lineAt(to).number; n <= last; n++) fn(doc.line(n), n === doc.lineAt(from).number, n === last);
    };
    const tree = ensureSyntaxTree(state, doc.length, 100) || syntaxTree(state);

    // Code is never parsed for references
    const code = [];
    tree.iterate({
        enter(node) {
            if (['FencedCode', 'CodeBlock', 'InlineCode'].includes(node.name)) { code.push([node.from, node.to]); return false; }
        },
    });
    const links = [];
    const text = doc.toString();
    for (const m of text.matchAll(WIKI)) {
        const from = m.index, to = m.index + m[0].length;
        if (code.some(([a, b]) => from < b && to > a)) continue;
        links.push({ from, to, embed: m[1] === '!', kind: m[2], value: m[3].trim(), label: (m[4] || '').trim() });
    }
    const inLink = (from, to) => links.some(l => from < l.to && to > l.from);

    tree.iterate({
        enter(node) {
            const name = node.name;
            if (INLINE.has(name) && inLink(node.from, node.to)) return false;

            const heading = /^(?:ATX|Setext)Heading(\d)$/.exec(name);
            if (heading) {
                eachLine(node.from, node.to, (line) => {
                    if (!/^\s*(=+|-+)\s*$/.test(line.text) || name.startsWith('ATX')) {
                        decos.push(Decoration.line({ class: `cm-md-h cm-md-h${heading[1]}` }).range(line.from));
                    }
                });
                return;
            }
            if (name === 'HeaderMark') {
                if (lineActive(node.from)) return;
                const line = doc.lineAt(node.from);
                if (node.node.parent?.name.startsWith('Setext')) { lineClass(node.from, 'cm-md-setext-line'); hide(node.from, node.to); return; }
                // "## " at the start, or closing "##" at the end
                if (node.from === line.from + (line.text.length - line.text.trimStart().length)) hide(node.from, Math.min(node.to + 1, line.to));
                else hide(Math.max(line.from, node.from - 1), node.to);
                return;
            }

            if (MARKED[name]) {
                decos.push(Decoration.mark({ class: MARKED[name] }).range(node.from, node.to));
                if (!touches(node.from, node.to)) {
                    for (const mark of node.node.getChildren(MARK_CHILD[name])) hide(mark.from, mark.to);
                }
                return name === 'InlineCode' ? false : undefined;
            }

            if (name === 'Link') {
                const marks = node.node.getChildren('LinkMark');
                const url = node.node.getChild('URL');
                if (!url || marks.length < 2) return; // [ref] links without a URL stay as typed
                const textFrom = marks[0].to, textTo = marks[1].from;
                const href = doc.sliceString(url.from, url.to);
                if (textFrom < textTo) decos.push(Decoration.mark({ class: 'cm-md-link', attributes: { 'data-href': href } }).range(textFrom, textTo));
                if (!touches(node.from, node.to)) { hide(node.from, textFrom); hide(textTo, node.to); }
                return false;
            }
            if (name === 'URL' && !['Link', 'Image'].includes(node.node.parent?.name)) {
                const href = doc.sliceString(node.from, node.to);
                decos.push(Decoration.mark({ class: 'cm-md-link', attributes: { 'data-href': href } }).range(node.from, node.to));
                return;
            }
            if (name === 'Autolink') {
                const marks = node.node.getChildren('LinkMark');
                if (!touches(node.from, node.to)) marks.forEach(mark => hide(mark.from, mark.to));
                return;
            }

            if (name === 'Image') {
                const url = node.node.getChild('URL');
                const marks = node.node.getChildren('LinkMark');
                const src = url ? doc.sliceString(url.from, url.to) : '';
                if ((/^https?:\/\//i.test(src) || NOTE_IMAGE_URL.test(src)) && !touches(node.from, node.to)) {
                    const alt = marks.length >= 2 ? doc.sliceString(marks[0].to, marks[1].from) : '';
                    decos.push(Decoration.replace({ widget: new ImageWidget(src, alt) }).range(node.from, node.to));
                }
                return false;
            }

            if (name === 'Blockquote') {
                eachLine(node.from, node.to, line => decos.push(Decoration.line({ class: 'cm-md-quote' }).range(line.from)));
                return;
            }
            if (name === 'QuoteMark') {
                if (!lineActive(node.from)) hide(node.from, doc.sliceString(node.to, node.to + 1) === ' ' ? node.to + 1 : node.to);
                return;
            }

            if (name === 'ListMark') {
                const item = node.node.parent;
                const active = lineActive(node.from);
                if (item?.getChild('Task')) {
                    if (!active) hide(node.from, node.to + 1);
                } else if (item?.parent?.name === 'BulletList' && !active) {
                    decos.push(Decoration.replace({ widget: new BulletWidget() }).range(node.from, node.to));
                } else {
                    decos.push(Decoration.mark({ class: 'cm-md-listmark' }).range(node.from, node.to));
                }
                return;
            }
            if (name === 'TaskMarker') {
                const checked = /x/i.test(doc.sliceString(node.from, node.to));
                if (checked) lineClass(node.from, 'cm-md-done');
                if (!touches(node.from, node.to)) decos.push(Decoration.replace({ widget: new CheckboxWidget(checked) }).range(node.from, node.to));
                return;
            }

            if (name === 'HorizontalRule') {
                if (!lineActive(node.from)) decos.push(Decoration.replace({ widget: new HrWidget() }).range(node.from, node.to));
                return;
            }

            if (name === 'FencedCode' || name === 'CodeBlock') {
                const active = touches(node.from, node.to);
                eachLine(node.from, node.to, (line, first, last) => {
                    const fence = name === 'FencedCode' && (first || last);
                    const cls = ['cm-md-codeblock', first && 'cm-md-codeblock-first', last && 'cm-md-codeblock-last', fence && !active && 'cm-md-fence'];
                    decos.push(Decoration.line({ class: cls.filter(Boolean).join(' ') }).range(line.from));
                });
                return false;
            }

            if (name === 'Table') {
                const from = doc.lineAt(node.from).from, to = doc.lineAt(node.to).to;
                if (!touches(from, to)) {
                    decos.push(Decoration.replace({ widget: new TableWidget(doc.sliceString(from, to), host), block: true }).range(from, to));
                } else {
                    eachLine(from, to, line => decos.push(Decoration.line({ class: 'cm-md-table-source' }).range(line.from)));
                }
                return false;
            }
        },
    });

    for (const link of links) {
        if (touches(link.from, link.to)) {
            decos.push(Decoration.mark({ class: 'cm-md-wiki-source' }).range(link.from, link.to));
            continue;
        }
        const line = doc.lineAt(link.from);
        const alone = line.text.trim() === doc.sliceString(link.from, link.to);
        if (link.embed && link.kind === 'snapshot' && alone) {
            decos.push(Decoration.replace({ widget: new EmbedWidget(link, host), block: true }).range(line.from, line.to));
        } else {
            decos.push(Decoration.replace({ widget: new ChipWidget(link, host) }).range(link.from, link.to));
        }
    }

    return Decoration.set(decos, true);
}

function livePreview(host) {
    return StateField.define({
        create: state => buildDecorations(state, host),
        update(decos, tr) {
            if (tr.docChanged || tr.selection || syntaxTree(tr.state) !== syntaxTree(tr.startState)) return buildDecorations(tr.state, host);
            return decos;
        },
        provide: field => EditorView.decorations.from(field),
    });
}

// ---------------------------------------------------------------------------
// [[ autocomplete
// ---------------------------------------------------------------------------

function referenceCompletion(host) {
    return async (context) => {
        const match = context.matchBefore(/!?\[\[[^\]\n]*/);
        if (!match) return null;
        const embed = match.text.startsWith('!');
        const query = match.text.slice(embed ? 3 : 2);
        const items = await host.complete(query, embed);
        if (!items || context.aborted) return null;
        return {
            from: match.from,
            filter: false,
            options: items.map(item => ({
                label: item.label,
                detail: item.detail,
                type: item.type,
                apply: (view, completion, from, to) => {
                    const end = view.state.sliceDoc(to, to + 2) === ']]' ? to + 2 : to;
                    const startDoc = view.state.doc;
                    Promise.resolve(item.text()).then((text) => {
                        if (!text) return;
                        // Snapshots are created on the server first; if the note changed meanwhile, insert at the cursor
                        const range = view.state.doc === startDoc ? { from, to: end } : { from: view.state.selection.main.head };
                        view.dispatch({ changes: { ...range, insert: text }, selection: { anchor: (range.from) + text.length } });
                        view.focus();
                    });
                },
            })),
        };
    };
}

// ---------------------------------------------------------------------------
// Commands, theme, editor
// ---------------------------------------------------------------------------

function wrapWith(marker) {
    return (view) => {
        view.dispatch(view.state.changeByRange((range) => {
            const text = view.state.sliceDoc(range.from, range.to);
            const wrapped = text.startsWith(marker) && text.endsWith(marker) && text.length >= marker.length * 2;
            const insert = wrapped ? text.slice(marker.length, -marker.length) : marker + text + marker;
            const anchor = range.empty ? range.from + marker.length : range.from;
            return { changes: { from: range.from, to: range.to, insert }, range: EditorSelection.range(anchor, range.empty ? anchor : range.from + insert.length) };
        }));
        return true;
    };
}

const highlight = HighlightStyle.define([
    { tag: tags.processingInstruction, color: '#6b7280' },
    { tag: tags.monospace, fontFamily: 'inherit' },
    { tag: tags.url, color: '#a78bfa' },
    { tag: tags.quote, color: '#cbd5e1' },
    { tag: tags.comment, color: '#6b7280' },
]);

const theme = EditorView.theme({
    '&': { height: '100%', color: '#e5e7eb', backgroundColor: 'transparent', fontSize: '0.9rem' },
    '&.cm-focused': { outline: 'none' },
    '.cm-scroller': { fontFamily: 'inherit', lineHeight: '1.65', overflow: 'auto' },
    '.cm-content': { padding: '1rem 1.1rem 4rem', caretColor: '#c084fc' },
    '.cm-line': { padding: '0' },
    '.cm-cursor': { borderLeftColor: '#c084fc', borderLeftWidth: '2px' },
    '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': { backgroundColor: 'rgba(147, 51, 234, 0.35) !important' },
    '.cm-placeholder': { color: '#6b7280' },
    // Above the notes sidebar (z-50); the [[ list is rendered into <body>, see tooltips() below
    '.cm-tooltip': { backgroundColor: '#14151f', border: '1px solid #293142', borderRadius: '8px', overflow: 'hidden', zIndex: '100' },
    '.cm-tooltip-autocomplete > ul': { fontFamily: 'inherit', maxHeight: '18rem', maxWidth: 'min(34rem, calc(100vw - 2rem))' },
    '.cm-tooltip-autocomplete > ul > li': { padding: '0.35rem 0.6rem !important', color: '#e5e7eb', overflow: 'hidden', textOverflow: 'ellipsis' },
    '.cm-tooltip-autocomplete > ul > li[aria-selected]': { backgroundColor: 'rgba(147, 51, 234, 0.3)', color: '#fff' },
    '.cm-completionDetail': { color: '#8b95a7', fontStyle: 'normal', marginLeft: '0.6rem' },
    '.cm-searchMatch': { backgroundColor: 'rgba(250, 204, 21, 0.25)' },
}, { dark: true });

// Files dropped or pasted into the note: a placeholder holds the place while each uploads
function addImages(view, files, pos, options) {
    if (!options.uploadImage) return;
    files.forEach((file, index) => {
        const label = `![Uploading ${file.name.replace(/[[\]()\n\r]/g, ' ')} (${Date.now()}-${index})…]()\n`;
        view.dispatch({ changes: { from: pos, insert: label } });
        pos += label.length;
        const replace = (text) => {
            const from = view.state.doc.toString().indexOf(label);
            if (from >= 0) view.dispatch({ changes: { from, to: from + label.length, insert: text } });
        };
        options.uploadImage(file).then(markdown => replace(`${markdown}\n`), () => replace(''));
    });
}

function fileDrag(event) {
    return Array.from(event.dataTransfer?.types || []).includes('Files');
}

function create(parent, options = {}) {
    const host = {
        renderChip: options.renderChip,
        renderEmbed: options.renderEmbed,
        complete: options.complete || (async () => []),
        renderInline: options.renderInline || (t => t.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))),
    };
    const extensions = [
        history(),
        drawSelection(),
        EditorView.lineWrapping,
        markdownLanguage,
        syntaxHighlighting(highlight),
        highlightSelectionMatches(),
        livePreview(host),
        autocompletion({ override: [referenceCompletion(host)], icons: false, activateOnTyping: true }),
        keymap.of([
            { key: 'Mod-b', run: wrapWith('**') },
            { key: 'Mod-i', run: wrapWith('*') },
            ...completionKeymap, ...markdownKeymap, ...searchKeymap, ...historyKeymap, ...defaultKeymap, indentWithTab,
        ]),
        placeholder(options.placeholder || ''),
        // The sidebar clips its content and is transformed (it slides in), which would
        // crop the [[ suggestions; render them into <body> instead
        tooltips({ parent: document.body }),
        theme,
        EditorView.updateListener.of((update) => {
            if (update.docChanged && options.onChange) options.onChange(update.state.doc.toString());
        }),
        // Rendered links open on click; once the cursor is inside one it is edited instead
        EditorView.domEventHandlers({
            dragover(event, view) {
                if (!fileDrag(event)) return false;
                event.preventDefault();
                view.dom.classList.add('cm-file-drag');
                return true;
            },
            dragleave(event, view) {
                if (!view.dom.contains(event.relatedTarget)) view.dom.classList.remove('cm-file-drag');
                return false;
            },
            drop(event, view) {
                view.dom.classList.remove('cm-file-drag');
                const files = Array.from(event.dataTransfer?.files || []);
                if (!files.length) return false;
                event.preventDefault();
                const at = view.posAtCoords({ x: event.clientX, y: event.clientY });
                addImages(view, files, view.state.doc.lineAt(at ?? view.state.selection.main.head).from, options);
                return true;
            },
            paste(event, view) {
                const files = Array.from(event.clipboardData?.files || []);
                if (!files.length) return false;
                event.preventDefault();
                addImages(view, files, view.state.doc.lineAt(view.state.selection.main.head).from, options);
                return true;
            },
            mousedown(event, view) {
                const link = event.target.closest('.cm-md-link');
                if (!link || event.button !== 0) return false;
                const pos = view.posAtDOM(link);
                if (view.state.selection.ranges.some(r => r.from <= pos + link.textContent.length && r.to >= pos)) return false;
                event.preventDefault();
                if (options.openLink) options.openLink(link.dataset.href);
                return true;
            },
        }),
    ];
    const view = new EditorView({ parent, state: EditorState.create({ doc: options.doc || '', extensions }) });

    return {
        view,
        getValue: () => view.state.doc.toString(),
        setValue(text) {
            view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text || '' }, selection: { anchor: 0 } });
        },
        // Inserts at the cursor; block content (embeds) goes on a line of its own
        insert(text, { block = false } = {}) {
            const { state } = view;
            const head = state.selection.main.head;
            let insert = text;
            if (block) {
                const line = state.doc.lineAt(head);
                insert = (line.text.trim() ? '\n' : '') + text + '\n';
                const pos = line.text.trim() ? line.to : line.from;
                view.dispatch({ changes: { from: pos, insert }, selection: { anchor: pos + insert.length } });
            } else {
                view.dispatch({ changes: { from: head, insert }, selection: { anchor: head + insert.length } });
            }
            view.focus();
        },
        focus: () => view.focus(),
        destroy: () => view.destroy(),
    };
}

window.NotesEditor = { create };
