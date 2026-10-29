// Notes: markdown notes per investigation, edited with Obsidian-style live preview
// (static/vendor/notes-editor.js, built from frontend/notes-editor, loaded on first use).
// Notes save themselves while you type. They can link results ([[result:<id>|label]])
// and identifiers ([[email:x@y.com]]), and attach snapshots of results
// (![[snapshot:<id>|label]]): a copy that stays in the note even if the result is deleted.
// Used by the Ctrl+K sidebar (every page) and the notes page (templates/notes.html).

const NOTES_EDITOR_SRC = "/static/vendor/notes-editor.js"
const NOTE_SAVE_DELAY = 800
const ENTITY_KINDS = /^(email|phone|username|domain|ip|url|name|telegram_username|telegram_id|wallet|vk_id|gaia_id)$/

let notesEditorLoading = null
function loadNotesEditor() {
  if (window.NotesEditor) return Promise.resolve()
  notesEditorLoading =
    notesEditorLoading ||
    new Promise((resolve, reject) => {
      const script = document.createElement("script")
      script.src = NOTES_EDITOR_SRC
      script.onload = resolve
      script.onerror = () => {
        notesEditorLoading = null
        reject(new Error("Could not load the notes editor"))
      }
      document.head.appendChild(script)
    })
  return notesEditorLoading
}

// The investigation page and notes page pin notes to the investigation being viewed
function notesInvestigationId() {
  return window.notesForInvestigation || (window.getCurrentInvestigationId && window.getCurrentInvestigationId()) || null
}

function notesApi(investigationId) {
  return `/api/investigations/${encodeURIComponent(investigationId)}`
}

// ---------------------------------------------------------------------------
// Results and snapshots of the investigation (for [[ completion, chips, embeds)
// ---------------------------------------------------------------------------

const noteResultsCache = new Map() // investigation id -> {at, promise of Map(result_id -> summary)}
const noteSnapshotCache = new Map() // snapshot id -> promise of snapshot
const openEmbeds = new Set() // snapshot ids shown expanded

function loadNoteResults(investigationId, { fresh = false } = {}) {
  const cached = noteResultsCache.get(investigationId)
  if (cached && !fresh && Date.now() - cached.at < 30000) return cached.promise
  const promise = fetch(`${notesApi(investigationId)}/results`)
    .then((r) => r.json())
    .then((data) => new Map((data.results || []).map((r) => [r.result_id, r])))
    .catch(() => new Map())
  noteResultsCache.set(investigationId, { at: Date.now(), promise })
  return promise
}

function loadSnapshot(investigationId, snapshotId) {
  if (!noteSnapshotCache.has(snapshotId)) {
    noteSnapshotCache.set(
      snapshotId,
      fetch(`${notesApi(investigationId)}/snapshots/${encodeURIComponent(snapshotId)}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => data && data.snapshot)
        .catch(() => null),
    )
  }
  return noteSnapshotCache.get(snapshotId)
}

async function createSnapshot(investigationId, resultId) {
  const response = await fetch(`${notesApi(investigationId)}/snapshots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ result_id: resultId }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
  return data.snapshot
}

function resultModuleName(service) {
  return typeof moduleInfo === "function" ? moduleInfo(service).name : String(service || "result")
}

function resultMethodName(method) {
  return typeof methodLabel === "function" ? methodLabel(method) : String(method || "").replace(/_/g, " ")
}

// Labels live inside [[...|label]], so they must not contain ] | or newlines
function resultLabel(result) {
  const target = result.target || resultMethodName(result.method_name)
  return `${resultModuleName(result.service_name)} · ${target}`.replace(/[\]|\n]/g, " ").trim()
}

function resultUrl(investigationId, resultId) {
  return `${notesApi(investigationId)}/view#result-${encodeURIComponent(resultId)}`
}

function noteDate(iso) {
  return iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : ""
}

// ---------------------------------------------------------------------------
// Rendering references inside the editor
// ---------------------------------------------------------------------------

function renderNoteChip(investigationId, results, link) {
  const wrap = document.createElement("span")
  wrap.className = "note-chip-wrap"
  if (link.kind === "result") {
    const result = results.get(link.value)
    const label = link.label || (result ? resultLabel(result) : link.value)
    if (result) {
      wrap.innerHTML = `<a class="note-chip" href="${escapeAttr(resultUrl(investigationId, link.value))}" title="${escapeAttr(`${resultModuleName(result.service_name)} · ${resultMethodName(result.method_name)}\n${result.summary || ""}\n${noteDate(result.timestamp)}`)}"><i class="fas fa-file-lines"></i>${escapeHtml(label)}</a>`
    } else {
      wrap.innerHTML = `<span class="note-chip note-chip-missing" title="This result was deleted"><i class="fas fa-link-slash"></i>${escapeHtml(label)}</span>`
    }
  } else if (link.kind === "snapshot") {
    wrap.innerHTML = `<span class="note-chip note-chip-snapshot" title="Snapshot - put it on a line of its own to show it"><i class="fas fa-paperclip"></i>${escapeHtml(link.label || "snapshot")}</span>`
  } else if (ENTITY_KINDS.test(link.kind) && typeof pivotChip === "function") {
    wrap.innerHTML = pivotChip(link.kind, link.value, link.label || null)
  } else {
    wrap.innerHTML = `<span class="note-chip">${escapeHtml(link.label || `${link.kind}:${link.value}`)}</span>`
  }
  return wrap
}

function renderSnapshotBody(snapshot) {
  const record = snapshot.record || {}
  const render = typeof safeRender === "function" ? safeRender : (s, m, data) => `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`
  const children = (record.children || [])
    .map(
      (child) => `
        <section class="mt-4">
          <h4 class="text-xs font-semibold text-purple-300 mb-2">${escapeHtml(resultMethodName(child.method_name))}</h4>
          ${render(child.service_name, child.method_name, child.result, child)}
        </section>`,
    )
    .join("")
  return render(record.service_name, record.method_name, record.result, record) + children
}

function renderNoteEmbed(investigationId, results, link, el) {
  el.innerHTML = `<div class="note-embed-head"><i class="fas fa-paperclip"></i><span class="note-embed-title">${escapeHtml(link.label || "Snapshot")}</span><span class="note-embed-meta">Loading…</span></div>`
  loadSnapshot(investigationId, link.value).then((snapshot) => {
    if (!snapshot) {
      el.classList.add("note-embed-missing")
      el.innerHTML = `
        <div class="note-embed-head"><i class="fas fa-triangle-exclamation"></i><span class="note-embed-title">${escapeHtml(link.label || "Snapshot")}</span>
          <span class="note-embed-meta">snapshot not found</span>
          <span class="note-embed-actions"><button type="button" data-embed-edit>Edit</button></span></div>`
      return
    }
    const original = results.has(snapshot.result_id)
    const open = openEmbeds.has(link.value)
    el.innerHTML = `
      <div class="note-embed-head">
        <i class="fas fa-paperclip"></i>
        <span class="note-embed-title" title="${escapeAttr(resultMethodName(snapshot.method_name))}">${escapeHtml(link.label || resultLabel(snapshot))}</span>
        <span class="note-embed-meta" title="Result from ${escapeAttr(noteDate(snapshot.timestamp))}, attached ${escapeAttr(noteDate(snapshot.created_at))}">snapshot · ${escapeHtml(noteDate(snapshot.timestamp))}</span>
        <span class="note-embed-actions">
          ${original ? `<a href="${escapeAttr(resultUrl(investigationId, snapshot.result_id))}" title="Open the result in the investigation">Original</a>` : '<span class="note-embed-gone" title="The result was deleted; this snapshot keeps a copy">original deleted</span>'}
          <button type="button" data-embed-toggle>${open ? "Hide" : "Show"}</button>
          <button type="button" data-embed-edit>Edit</button>
        </span>
      </div>
      ${snapshot.summary ? `<div class="note-embed-summary">${escapeHtml(snapshot.summary)}</div>` : ""}
      <div class="note-embed-body ${open ? "" : "hidden"}"></div>`
    const body = el.querySelector(".note-embed-body")
    const fill = () => {
      if (body.dataset.filled) return
      body.dataset.filled = "1"
      body.innerHTML = renderSnapshotBody(snapshot)
      if (typeof masonryPackAll === "function") masonryPackAll(body)
      if (window.lucide) lucide.createIcons()
    }
    if (open) requestAnimationFrame(fill)
    el.querySelector("[data-embed-toggle]").addEventListener("click", (event) => {
      const show = body.classList.contains("hidden")
      body.classList.toggle("hidden", !show)
      event.currentTarget.textContent = show ? "Hide" : "Show"
      if (show) {
        openEmbeds.add(link.value)
        fill()
      } else {
        openEmbeds.delete(link.value)
      }
    })
  })
}

function renderNoteInline(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
}

// [[ completion: results, then identifiers. ![[ attaches a snapshot of a result.
async function completeNoteReference(investigationId, query, embed) {
  const needle = query.trim().toLowerCase()
  const results = [...(await loadNoteResults(investigationId)).values()]
  const matches = results
    .filter((r) => {
      if (!needle) return true
      const text = [resultModuleName(r.service_name), resultMethodName(r.method_name), r.target, r.summary, r.service_name].join(" ").toLowerCase()
      return needle.split(/\s+/).every((word) => text.includes(word))
    })
    .slice(0, embed ? 30 : 15)
    .map((r) => {
      const label = resultLabel(r)
      return {
        label,
        detail: `${embed ? "attach snapshot · " : ""}${r.summary || ""} · ${noteDate(r.timestamp)}`,
        type: "result",
        text: embed
          ? () =>
              createSnapshot(investigationId, r.result_id)
                .then((snapshot) => `![[snapshot:${snapshot.snapshot_id}|${label}]]`)
                .catch((error) => {
                  showTemporaryNotification(`Could not attach the result: ${error.message}`, "error")
                  return null
                })
          : () => `[[result:${r.result_id}|${label}]]`,
      }
    })
  if (embed) return matches
  let entities = []
  try {
    const data = await fetch(`${notesApi(investigationId)}/entities?limit=15${needle ? `&q=${encodeURIComponent(needle)}` : ""}`).then((r) => r.json())
    entities = (data.entities || [])
      .filter((e) => !/[\]|\n]/.test(e.value))
      .map((e) => ({ label: e.value, detail: e.label || e.type, type: "entity", text: () => `[[${e.type}:${e.value}]]` }))
  } catch (error) {
    // identifiers are optional here
  }
  return [...matches, ...entities]
}

// ---------------------------------------------------------------------------
// A note editor with autosave (sidebar and notes page)
// ---------------------------------------------------------------------------

function noteTitle(content) {
  const line = content.split("\n").find((l) => l.trim()) || ""
  const title = line
    .replace(/^#+\s*/, "")
    .replace(/!?\[\[[a-z_]+:[^\]|]+\|([^\]]*)\]\]/g, "$1")
    .replace(/!?\[\[[a-z_]+:([^\]|]+)\]\]/g, "$1")
    .replace(/[*_`~>]/g, "")
    .trim()
  return title.slice(0, 80) || "Untitled note"
}

class NotePad {
  constructor(container, { statusEl = null, investigationId = null, onSaved = null, onOpened = null } = {}) {
    this.container = container
    this.statusEl = statusEl
    this.fixedInvestigationId = investigationId
    this.onSaved = onSaved
    this.onOpened = onOpened
    this.editor = null
    this.noteId = null
    this.version = 0
    this.savedVersion = 0
    this.timer = null
    this.saving = null
    this.loading = false
  }

  investigationId() {
    return this.fixedInvestigationId || notesInvestigationId()
  }

  async ready() {
    if (this.editor) return
    await loadNotesEditor()
    if (this.editor) return
    const investigation = () => this.investigationId()
    const results = await loadNoteResults(investigation())
    this.results = results
    this.editor = NotesEditor.create(this.container, {
      placeholder: "Start writing…  Type [[ to link a result or identifier, ![[ to attach a snapshot of a result.",
      onChange: () => this.changed(),
      renderChip: (link) => renderNoteChip(investigation(), this.results, link),
      renderEmbed: (link, el) => renderNoteEmbed(investigation(), this.results, link, el),
      complete: (query, embed) => completeNoteReference(investigation(), query, embed),
      renderInline: renderNoteInline,
      openLink: (href) => {
        const url = safeUrl(href)
        if (url) window.open(url, "_blank", "noopener,noreferrer")
      },
    })
  }

  status(text) {
    if (this.statusEl) this.statusEl.textContent = text
  }

  get dirty() {
    return this.version !== this.savedVersion
  }

  changed() {
    if (this.loading) return
    this.version += 1
    this.status("Editing…")
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.save(), NOTE_SAVE_DELAY)
  }

  async refreshResults() {
    this.results = await loadNoteResults(this.investigationId(), { fresh: true })
  }

  async open(noteId) {
    await this.ready()
    await this.flush()
    const investigationId = this.investigationId()
    const data = await fetch(`${notesApi(investigationId)}/notes/${encodeURIComponent(noteId)}`).then((r) => r.json())
    if (data.status !== "success" || !data.note) throw new Error("Note not found")
    await this.refreshResults()
    this.setContent(noteId, data.note.content || "")
    this.status(`Saved ${noteDate(data.note.updated_at)}`)
    if (this.onOpened) this.onOpened(data.note)
    return data.note
  }

  async newNote() {
    await this.ready()
    await this.flush()
    this.setContent(null, "")
    this.status("New note")
    if (this.onOpened) this.onOpened(null)
    this.editor.focus()
  }

  setContent(noteId, content) {
    this.loading = true
    this.noteId = noteId
    this.editor.setValue(content)
    this.loading = false
    this.version = this.savedVersion = 0
    const investigationId = this.investigationId()
    try {
      if (noteId) localStorage.setItem(`notes:last:${investigationId}`, noteId)
      else localStorage.removeItem(`notes:last:${investigationId}`)
    } catch (error) {
      // remembering the last note is a convenience only
    }
  }

  async flush() {
    clearTimeout(this.timer)
    if (this.saving) await this.saving
    if (this.dirty) await this.save()
  }

  save() {
    if (this.saving) return this.saving
    this.saving = this.doSave().finally(() => {
      this.saving = null
      if (this.dirty) this.timer = setTimeout(() => this.save(), NOTE_SAVE_DELAY)
    })
    return this.saving
  }

  async doSave() {
    clearTimeout(this.timer)
    const investigationId = this.investigationId()
    if (!this.editor || !this.dirty || !investigationId) return
    const version = this.version
    const content = this.editor.getValue()
    if (!content.trim() && !this.noteId) {
      this.savedVersion = version
      this.status("New note")
      return
    }
    this.status("Saving…")
    const body = JSON.stringify({ title: noteTitle(content), content, note_type: "manual", tags: [] })
    try {
      const created = !this.noteId
      const response = await fetch(
        created ? `${notesApi(investigationId)}/notes` : `${notesApi(investigationId)}/notes/${encodeURIComponent(this.noteId)}`,
        { method: created ? "POST" : "PUT", headers: { "Content-Type": "application/json" }, body },
      )
      const data = await response.json().catch(() => ({}))
      if (data.status !== "success") throw new Error(data.detail || data.message || `HTTP ${response.status}`)
      if (created) {
        this.noteId = data.note_id
        try {
          localStorage.setItem(`notes:last:${investigationId}`, this.noteId)
        } catch (error) {
          // convenience only
        }
      }
      this.savedVersion = version
      this.status("Saved")
      if (this.onSaved) this.onSaved({ noteId: this.noteId, title: noteTitle(content), created })
    } catch (error) {
      console.error("Error saving note:", error)
      this.status("Not saved - retrying")
      this.timer = setTimeout(() => this.save(), 5000)
    }
  }

  // Leaving the page: send what is unsaved without waiting for an answer
  saveOnUnload() {
    const investigationId = this.investigationId()
    if (!this.editor || !this.dirty || !investigationId) return
    const content = this.editor.getValue()
    if (!content.trim() && !this.noteId) return
    fetch(this.noteId ? `${notesApi(investigationId)}/notes/${encodeURIComponent(this.noteId)}` : `${notesApi(investigationId)}/notes`, {
      method: this.noteId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: noteTitle(content), content, note_type: "manual", tags: [] }),
      keepalive: true,
    })
  }

  insert(text, options) {
    this.editor.insert(text, options)
  }
}

// Markdown for use outside the app: links become URLs, snapshots become quoted summaries
async function exportNoteMarkdown(investigationId, content) {
  const origin = window.location.origin
  const snapshots = {}
  for (const [, id] of content.matchAll(/!\[\[snapshot:([0-9a-f]{32})(?:\|[^\]]*)?\]\]/g)) {
    snapshots[id] = await loadSnapshot(investigationId, id)
  }
  return content
    .replace(/!\[\[snapshot:([0-9a-f]{32})(?:\|([^\]]*))?\]\]/g, (m, id, label) => {
      const s = snapshots[id]
      if (!s) return `> **Snapshot:** ${label || id} (missing)`
      return [
        `> **Snapshot: ${label || resultLabel(s)}**`,
        `> ${resultModuleName(s.service_name)}, ${resultMethodName(s.method_name)} · result from ${noteDate(s.timestamp)}`,
        s.summary ? `> ${s.summary}` : null,
      ]
        .filter(Boolean)
        .join("\n")
    })
    .replace(/\[\[result:([^\]|]+)(?:\|([^\]]*))?\]\]/g, (m, id, label) => `[${label || id}](${origin}${resultUrl(investigationId, id)})`)
    .replace(/\[\[[a-z_]+:([^\]|]+)(?:\|([^\]]*))?\]\]/g, (m, value, label) => `\`${label || value}\``)
}

// ---------------------------------------------------------------------------
// Sidebar (Ctrl+K)
// ---------------------------------------------------------------------------

let sidebarPad = null

function getSidebarPad() {
  if (!sidebarPad) {
    sidebarPad = new NotePad(document.getElementById("noteEditorHost"), {
      statusEl: document.getElementById("noteSaveStatus"),
      onSaved: ({ created }) => {
        loadSavedNotes()
        if (created) document.dispatchEvent(new CustomEvent("notes:changed"))
      },
      onOpened: () => highlightOpenNote(),
    })
  }
  return sidebarPad
}

function sidebarIsOpen() {
  const sidebar = document.getElementById("noteSidebar")
  return sidebar && !sidebar.classList.contains("translate-x-full")
}

function toggleNoteSidebar() {
  if (sidebarIsOpen()) closeNoteSidebar()
  else openNoteSidebar()
}

async function openNoteSidebar() {
  const investigationId = notesInvestigationId()
  if (!investigationId) {
    showTemporaryNotification("Please select an investigation first", "error")
    return false
  }
  const sidebar = document.getElementById("noteSidebar")
  const backdrop = document.getElementById("noteSidebarBackdrop")
  backdrop.classList.remove("hidden")
  setTimeout(() => {
    backdrop.classList.remove("opacity-0")
    sidebar.classList.remove("translate-x-full")
  }, 10)
  document.getElementById("noteFullPageLink").href = `${notesApi(investigationId)}/notes/view`
  loadSavedNotes()

  const pad = getSidebarPad()
  try {
    const firstOpen = !pad.editor
    await pad.ready()
    if (firstOpen || pad.openedFor !== investigationId) {
      pad.openedFor = investigationId
      let last = null
      try {
        last = localStorage.getItem(`notes:last:${investigationId}`)
      } catch (error) {
        // convenience only
      }
      if (last) await pad.open(last).catch(() => pad.newNote())
      else await pad.newNote()
    } else {
      await pad.refreshResults()
    }
    pad.editor.focus()
  } catch (error) {
    document.getElementById("noteEditorHost").innerHTML = `<p class="p-4 text-sm text-red-300">${escapeHtml(error.message)}</p>`
  }
  return true
}

function closeNoteSidebar() {
  const sidebar = document.getElementById("noteSidebar")
  const backdrop = document.getElementById("noteSidebarBackdrop")
  backdrop.classList.add("opacity-0")
  sidebar.classList.add("translate-x-full")
  setTimeout(() => backdrop.classList.add("hidden"), 300)
  if (sidebarPad) sidebarPad.flush()
}

async function newSidebarNote() {
  await getSidebarPad().newNote()
  highlightOpenNote()
}

async function openSidebarNote(noteId) {
  try {
    await getSidebarPad().open(noteId)
  } catch (error) {
    showTemporaryNotification("Failed to open the note", "error")
  }
}

function highlightOpenNote() {
  const current = sidebarPad && sidebarPad.noteId
  document.querySelectorAll("#savedNotesList [data-note-id]").forEach((el) => {
    el.classList.toggle("note-list-active", el.dataset.noteId === current)
  })
}

async function loadSavedNotes() {
  const investigationId = notesInvestigationId()
  const container = document.getElementById("savedNotesList")
  if (!container) return
  if (!investigationId) {
    container.innerHTML = '<div class="text-xs text-gray-500 text-center py-2">Select an investigation to view notes</div>'
    return
  }
  try {
    const data = await fetch(`${notesApi(investigationId)}/notes`).then((r) => r.json())
    if (data.status !== "success") throw new Error("Failed to load notes")
    const notes = (data.notes || []).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
    container.innerHTML = notes.length
      ? notes
          .map(
            (note) => `
          <div class="note-list-item group" data-note-id="${escapeAttr(note.note_id)}" onclick="openSidebarNote('${escapeAttr(note.note_id)}')">
            <div class="flex-1 min-w-0">
              <div class="text-sm text-white truncate">${escapeHtml(note.title || "Untitled note")}</div>
              <div class="text-xs text-gray-500">${escapeHtml(noteDate(note.updated_at))}</div>
            </div>
            <button type="button" onclick="deleteNote('${escapeAttr(note.note_id)}', event)" title="Delete note"
                    class="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 transition-all ml-2">
              <i class="fas fa-trash text-xs"></i>
            </button>
          </div>`,
          )
          .join("")
      : '<div class="text-xs text-gray-500 text-center py-2">No notes yet</div>'
    highlightOpenNote()
  } catch (error) {
    console.error("Error loading notes:", error)
    container.innerHTML = '<div class="text-xs text-red-400 text-center py-2">Failed to load notes</div>'
  }
}

async function deleteNote(noteId, event) {
  if (event) event.stopPropagation()
  const investigationId = notesInvestigationId()
  if (!investigationId || !confirm("Delete this note?")) return false
  try {
    const response = await fetch(`${notesApi(investigationId)}/notes/${encodeURIComponent(noteId)}`, { method: "DELETE" })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    if (sidebarPad && sidebarPad.noteId === noteId) {
      sidebarPad.version = sidebarPad.savedVersion
      await sidebarPad.newNote()
    }
    await loadSavedNotes()
    document.dispatchEvent(new CustomEvent("notes:changed"))
    showTemporaryNotification("Note deleted", "success")
    return true
  } catch (error) {
    console.error("Error deleting note:", error)
    showTemporaryNotification("Failed to delete note", "error")
    return false
  }
}

// "Link in note" / "Attach to note" on results: adds to the note open in the sidebar
async function addResultToNote(resultId, { snapshot = false } = {}) {
  if (!(await openNoteSidebar())) return
  const pad = getSidebarPad()
  const investigationId = pad.investigationId()
  try {
    await pad.ready()
    await pad.refreshResults()
    const result = pad.results.get(resultId)
    if (!result) throw new Error("result not found in this investigation")
    const label = resultLabel(result)
    if (snapshot) {
      const snap = await createSnapshot(investigationId, resultId)
      pad.insert(`![[snapshot:${snap.snapshot_id}|${label}]]`, { block: true })
      showTemporaryNotification("Snapshot attached to the note", "success")
    } else {
      pad.insert(`[[result:${resultId}|${label}]] `)
    }
  } catch (error) {
    showTemporaryNotification(`Could not add the result: ${error.message}`, "error")
  }
}
window.addResultToNote = addResultToNote

document.addEventListener("DOMContentLoaded", () => {
  const originalSelectInvestigation = window.selectInvestigation
  if (originalSelectInvestigation) {
    window.selectInvestigation = async (...args) => {
      if (sidebarPad) await sidebarPad.flush()
      return originalSelectInvestigation(...args)
    }
  }
})

window.addEventListener("pagehide", () => {
  if (sidebarPad) sidebarPad.saveOnUnload()
})

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault()
    toggleNoteSidebar()
  }
  if ((e.ctrlKey || e.metaKey) && e.key === "s" && sidebarIsOpen()) {
    e.preventDefault()
    getSidebarPad().flush()
  }
  // The editor handles Escape first when it closes its [[ suggestions
  if (e.key === "Escape" && sidebarIsOpen() && !e.defaultPrevented) {
    closeNoteSidebar()
  }
})
