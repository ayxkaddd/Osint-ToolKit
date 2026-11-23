// Notes page (notes.html): the investigation's notes and the editor
// Own scope: notes.js (on every page) has the shared NotePad and helpers
(function () {
    const investigationId = pageData('investigationId');
    window.notesForInvestigation = investigationId;
    const api = `/api/investigations/${investigationId}`;
    const $ = (id) => document.getElementById(id);
    let notes = [];

    const pad = new NotePad($('notesPageEditor'), {
        investigationId,
        statusEl: $('noteStatus'),
        onSaved: () => loadNotes(),
        onOpened: (note) => {
            history.replaceState(null, '', note ? `#note-${note.note_id}` : location.pathname);
            renderList();
        },
    });

    async function loadInvestigationInfo() {
        try {
            const data = await fetch(`${api}/info`).then((r) => r.json());
            if (data.status === 'success') $('investigationInfo').textContent = data.investigation.name;
        } catch (error) {
            $('investigationInfo').textContent = '';
        }
    }

    async function loadNotes() {
        try {
            const data = await fetch(`${api}/notes`).then((r) => r.json());
            notes = (data.notes || []).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
        } catch (error) {
            notes = [];
        }
        renderList();
    }

    function renderList() {
        const needle = $('noteSearch').value.trim().toLowerCase();
        const shown = notes.filter((n) => !needle || `${n.title}\n${n.content}`.toLowerCase().includes(needle));
        $('notesList').innerHTML = shown.length
            ? shown
                  .map(
                      (note) => `
            <div class="note-list-item ${note.note_id === pad.noteId ? 'note-list-active' : ''}" data-open-note="${escapeAttr(note.note_id)}">
                <div class="min-w-0">
                    <div class="text-sm text-white truncate">${escapeHtml(note.title || 'Untitled note')}</div>
                    <div class="text-xs text-gray-500">${escapeHtml(noteDate(note.updated_at))}</div>
                </div>
            </div>`
                  )
                  .join('')
            : `<p class="text-xs text-gray-500 text-center py-4">${notes.length ? 'No notes match' : 'No notes yet'}</p>`;
    }

    $('notesList').addEventListener('click', (event) => {
        const item = event.target.closest('[data-open-note]');
        if (item)
            pad.open(item.dataset.openNote).catch(() => showTemporaryNotification('Failed to open the note', 'error'));
    });
    $('noteSearch').addEventListener('input', renderList);
    $('newNoteBtn').addEventListener('click', () => pad.newNote());

    $('deleteNoteBtn').addEventListener('click', async () => {
        if (!pad.noteId || !(await confirmDeleteNote(investigationId, pad.noteId))) return;
        const response = await fetch(`${api}/notes/${encodeURIComponent(pad.noteId)}`, { method: 'DELETE' });
        if (!response.ok) return showTemporaryNotification('Failed to delete note', 'error');
        pad.version = pad.savedVersion;
        await pad.newNote();
        await loadNotes();
        showTemporaryNotification('Note deleted', 'success');
    });

    $('exportNoteBtn').addEventListener('click', async () => {
        const content = pad.editor ? pad.editor.getValue() : '';
        if (!content.trim()) return;
        const markdown = await exportNoteMarkdown(investigationId, content);
        const name =
            noteTitle(content)
                .replace(/[^\w\- ]+/g, '')
                .trim()
                .replace(/\s+/g, '_') || 'note';
        const link = document.createElement('a');
        link.href = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }));
        link.download = `${name}.md`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    });

    window.addEventListener('pagehide', () => pad.saveOnUnload());
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 's' && !sidebarIsOpen()) {
            e.preventDefault();
            pad.flush();
        }
    });
    // Notes added or deleted from the sidebar
    document.addEventListener('notes:changed', loadNotes);

    (async () => {
        loadInvestigationInfo();
        await loadNotes();
        const linked = /^#note-([0-9a-f-]{36})$/.exec(location.hash);
        const first = linked ? linked[1] : notes[0] && notes[0].note_id;
        try {
            if (first) await pad.open(first);
            else await pad.newNote();
        } catch (error) {
            await pad.newNote();
        }
    })();
})();
