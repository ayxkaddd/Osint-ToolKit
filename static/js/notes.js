// Quick Notes functionality with markdown support - Backend integrated

let currentNoteId = null

// marked loads with `async` (a slow CDN must not hold up the page), so look it up when rendering.
// Notes can hold pasted target content: raw HTML is shown as text and only
// http(s)/mailto/tel links survive.
let markedConfigured = false
function renderMarkdown(text) {
  const md = window.marked
  if (!md || typeof md.parse !== "function") {
    return `<pre class="whitespace-pre-wrap">${escapeHtml(text)}</pre>`
  }
  if (!markedConfigured) {
    md.use({ renderer: { html: (token) => escapeHtml(token.raw || token.text || "") } })
    markedConfigured = true
  }
  const template = document.createElement("template")
  template.innerHTML = md.parse(text)
  template.content.querySelectorAll("a[href]").forEach((a) => {
    const href = safeUrl(a.getAttribute("href"))
    if (href) {
      a.setAttribute("href", href)
      a.setAttribute("target", "_blank")
      a.setAttribute("rel", "noopener noreferrer")
    } else {
      a.removeAttribute("href")
    }
  })
  template.content.querySelectorAll("img[src]").forEach((img) => {
    if (!/^https?:/i.test(img.getAttribute("src"))) img.remove()
  })
  return template.innerHTML
}

function getCurrentInvestigationId() {
  return window.currentInvestigationId || localStorage.getItem("currentInvestigationId")
}

// function showTemporaryNotification(message, type) {
//   const notification = document.createElement("div")
//   notification.className = `fixed top-20 right-4 z-50 px-4 py-3 rounded-lg shadow-lg transition-all duration-300 ${
//     type === "success" ? "bg-green-600" : type === "error" ? "bg-red-600" : "bg-blue-600"
//   } text-white font-medium`
//   notification.textContent = message

//   document.body.appendChild(notification)

//   setTimeout(() => {
//     notification.style.opacity = "0"
//     setTimeout(() => notification.remove(), 300)
//   }, 3000)
// }

// Initialize notes on page load
document.addEventListener("DOMContentLoaded", () => {
  loadSavedNotes()

  // Auto-save to localStorage as user types (draft only)
  const editor = document.getElementById("noteEditor")
  if (editor) {
    editor.addEventListener(
      "input",
      debounce(() => {
        localStorage.setItem("quickNotesDraft", editor.value)
      }, 500),
    )

    // Load draft if exists
    const draft = localStorage.getItem("quickNotesDraft")
    if (draft) {
      editor.value = draft
    }
  }

  const originalSelectInvestigation = window.selectInvestigation
  if (originalSelectInvestigation) {
    window.selectInvestigation = (...args) => {
      originalSelectInvestigation(...args)
      setTimeout(() => {
        loadSavedNotes()
        clearNoteEditor()
      }, 500)
    }
  }
})

// Toggle note sidebar
function toggleNoteSidebar() {
  const sidebar = document.getElementById("noteSidebar")
  const backdrop = document.getElementById("noteSidebarBackdrop")

  if (sidebar.classList.contains("translate-x-full")) {
    openNoteSidebar()
  } else {
    closeNoteSidebar()
  }
}

function openNoteSidebar() {
  const investigationId = getCurrentInvestigationId()
  if (!investigationId) {
    showTemporaryNotification("Please select an investigation first", "error")
    return
  }

  const sidebar = document.getElementById("noteSidebar")
  const backdrop = document.getElementById("noteSidebarBackdrop")

  backdrop.classList.remove("hidden")
  setTimeout(() => {
    backdrop.classList.remove("opacity-0")
    sidebar.classList.remove("translate-x-full")
  }, 10)

  loadSavedNotes()
}

function closeNoteSidebar() {
  const sidebar = document.getElementById("noteSidebar")
  const backdrop = document.getElementById("noteSidebarBackdrop")

  backdrop.classList.add("opacity-0")
  sidebar.classList.add("translate-x-full")

  setTimeout(() => {
    backdrop.classList.add("hidden")
  }, 300)
}

// Switch between write and preview tabs
function switchNoteTab(tab) {
  const writeTab = document.getElementById("writeTab")
  const previewTab = document.getElementById("previewTab")
  const writeView = document.getElementById("noteWriteView")
  const previewView = document.getElementById("notePreviewView")
  const editor = document.getElementById("noteEditor")
  const preview = document.getElementById("notePreview")

  if (tab === "write") {
    writeTab.classList.add("border-purple-500", "text-purple-400")
    writeTab.classList.remove("border-transparent", "text-gray-400")
    previewTab.classList.remove("border-purple-500", "text-purple-400")
    previewTab.classList.add("border-transparent", "text-gray-400")

    writeView.classList.remove("hidden")
    previewView.classList.add("hidden")
  } else {
    previewTab.classList.add("border-purple-500", "text-purple-400")
    previewTab.classList.remove("border-transparent", "text-gray-400")
    writeTab.classList.remove("border-purple-500", "text-purple-400")
    writeTab.classList.add("border-transparent", "text-gray-400")

    writeView.classList.add("hidden")
    previewView.classList.remove("hidden")

    // Render markdown
    const markdown = editor.value || "*No content to preview*"
    preview.innerHTML = renderMarkdown(markdown)
  }
}

async function saveNote() {
  const investigationId = getCurrentInvestigationId()
  if (!investigationId) {
    showTemporaryNotification("Please select an investigation first", "error")
    return
  }

  const editor = document.getElementById("noteEditor")
  const content = editor.value.trim()

  if (!content) {
    showTemporaryNotification("Please write something before saving", "error")
    return
  }

  // Extract title from first line or first heading
  let title = "Untitled Note"
  const lines = content.split("\n")
  for (let line of lines) {
    line = line.trim()
    if (line) {
      title = line.replace(/^#+\s*/, "").substring(0, 50)
      break
    }
  }

  try {
    const endpoint = currentNoteId
      ? `/api/investigations/${investigationId}/notes/${currentNoteId}`
      : `/api/investigations/${investigationId}/notes`

    const method = currentNoteId ? "PUT" : "POST"

    const response = await fetch(endpoint, {
      method: method,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        title: title,
        content: content,
        note_type: "manual",
        tags: [],
      }),
    })

    const data = await response.json()

    if (data.status === "success") {
      showTemporaryNotification("Note saved successfully!", "success")
      localStorage.removeItem("quickNotesDraft")
      await loadSavedNotes()
      clearNoteEditor()
    } else {
      throw new Error(data.message || "Failed to save note")
    }
  } catch (error) {
    console.error("Error saving note:", error)
    showTemporaryNotification("Failed to save note", "error")
  }
}

async function loadSavedNotes() {
  const investigationId = getCurrentInvestigationId()
  const container = document.getElementById("savedNotesList")

  if (!container) return

  if (!investigationId) {
    container.innerHTML =
      '<div class="text-xs text-gray-500 text-center py-2">Select an investigation to view notes</div>'
    return
  }

  // Show loading state
  container.innerHTML =
    '<div class="text-xs text-gray-500 text-center py-2"><i class="fas fa-spinner fa-spin mr-2"></i>Loading notes...</div>'

  try {
    const response = await fetch(`/api/investigations/${investigationId}/notes?note_type=manual`)
    const data = await response.json()

    if (data.status === "success" && data.notes) {
      const notes = data.notes

      if (notes.length === 0) {
        container.innerHTML = '<div class="text-xs text-gray-500 text-center py-2">No saved notes yet</div>'
        return
      }

      container.innerHTML = notes
        .map((note) => {
          const date = new Date(note.created_at)
          const dateStr =
            date.toLocaleDateString() + " " + date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })

          return `
          <div class="bg-gray-800/50 rounded p-2 hover:bg-gray-800 transition-colors cursor-pointer group"
               onclick="loadNoteToEditor('${note.note_id}')">
              <div class="flex items-start justify-between">
                  <div class="flex-1 min-w-0">
                      <div class="text-sm font-medium text-white truncate">${escapeHtml(note.title)}</div>
                      <div class="text-xs text-gray-500 mt-1">${dateStr}</div>
                  </div>
                  <button onclick="deleteNote('${note.note_id}', event)" 
                          class="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 transition-all ml-2">
                      <i class="fas fa-trash text-xs"></i>
                  </button>
              </div>
          </div>
        `
        })
        .join("")
    } else {
      throw new Error("Failed to load notes")
    }
  } catch (error) {
    console.error("Error loading notes:", error)
    container.innerHTML = '<div class="text-xs text-red-400 text-center py-2">Failed to load notes</div>'
  }
}

async function loadNoteToEditor(noteId) {
  const investigationId = getCurrentInvestigationId()
  if (!investigationId) return

  try {
    const response = await fetch(`/api/investigations/${investigationId}/notes/${noteId}`)
    const data = await response.json()

    if (data.status === "success" && data.note) {
      const editor = document.getElementById("noteEditor")
      editor.value = data.note.content
      currentNoteId = noteId

      switchNoteTab("write")
      showTemporaryNotification("Note loaded", "success")
    }
  } catch (error) {
    console.error("Error loading note:", error)
    showTemporaryNotification("Failed to load note", "error")
  }
}

async function deleteNote(noteId, event) {
  event.stopPropagation()

  const investigationId = getCurrentInvestigationId()
  if (!investigationId) return

  if (!confirm("Are you sure you want to delete this note?")) {
    return
  }

  try {
    const response = await fetch(`/api/investigations/${investigationId}/notes/${noteId}`, {
      method: "DELETE",
    })

    const data = await response.json()

    if (data.status === "success") {
      if (currentNoteId === noteId) {
        clearNoteEditor()
      }
      await loadSavedNotes()
      showTemporaryNotification("Note deleted", "success")
    } else {
      throw new Error("Failed to delete note")
    }
  } catch (error) {
    console.error("Error deleting note:", error)
    showTemporaryNotification("Failed to delete note", "error")
  }
}

async function clearAllNotes() {
  const investigationId = getCurrentInvestigationId()
  if (!investigationId) return

  if (!confirm("Are you sure you want to delete all notes for this investigation? This cannot be undone.")) {
    return
  }

  try {
    // Fetch all notes first
    const response = await fetch(`/api/investigations/${investigationId}/notes?note_type=manual`)
    const data = await response.json()

    if (data.status === "success" && data.notes) {
      // Delete each note
      const deletePromises = data.notes.map((note) =>
        fetch(`/api/investigations/${investigationId}/notes/${note.note_id}`, {
          method: "DELETE",
        }),
      )

      await Promise.all(deletePromises)

      clearNoteEditor()
      await loadSavedNotes()
      showTemporaryNotification("All notes cleared", "success")
    }
  } catch (error) {
    console.error("Error clearing notes:", error)
    showTemporaryNotification("Failed to clear notes", "error")
  }
}

function clearNoteEditor() {
  const editor = document.getElementById("noteEditor")
  editor.value = ""
  currentNoteId = null
  localStorage.removeItem("quickNotesDraft")
  switchNoteTab("write")
}

function debounce(func, wait) {
  let timeout
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout)
      func(...args)
    }
    clearTimeout(timeout)
    timeout = setTimeout(later, wait)
  }
}

document.addEventListener("keydown", (e) => {
  // Ctrl/Cmd + K to open notes
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault()
    toggleNoteSidebar()
  }

  // Ctrl/Cmd + S to save note when sidebar is open
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    const sidebar = document.getElementById("noteSidebar")
    if (!sidebar.classList.contains("translate-x-full")) {
      e.preventDefault()
      saveNote()
    }
  }

  // Escape to close sidebar
  if (e.key === "Escape") {
    const sidebar = document.getElementById("noteSidebar")
    if (!sidebar.classList.contains("translate-x-full")) {
      closeNoteSidebar()
    }
  }
})
