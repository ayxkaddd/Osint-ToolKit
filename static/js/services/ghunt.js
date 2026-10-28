document.addEventListener("DOMContentLoaded", () => {
  const lucide = window.lucide
  lucide.createIcons()

  let currentModule = "email"
  let currentData = null

  const moduleConfigs = {
    email: {
      placeholder: "Enter email address",
      hint: "Search for information about a Google account using their email address",
      endpoint: "/api/ghunt/email",
      param: "email",
    },
    gaia: {
      placeholder: "Enter Gaia ID",
      hint: "Search for information about a Google account using their Gaia ID",
      endpoint: "/api/ghunt/gaia",
      param: "gaia_id",
    },
  }

  // Enable result loading
  window.currentService = "ghunt"
  window.loadResultIntoView = (data) => {
    displayResults(currentModule, data)
  }

  setupEventListeners()
  updateModuleUI()

  function setupEventListeners() {
    // Module tabs
    document.querySelectorAll(".module-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        currentModule = tab.dataset.module
        updateModuleUI()
        document.querySelectorAll(".module-tab").forEach((t) => t.classList.remove("active"))
        tab.classList.add("active")
      })
    })

    // Search
    document.getElementById("searchButton").addEventListener("click", performSearch)
    document.getElementById("searchInput").addEventListener("keypress", (e) => {
      if (e.key === "Enter") performSearch()
    })
  }

  function updateModuleUI() {
    const config = moduleConfigs[currentModule]
    document.getElementById("searchInput").placeholder = config.placeholder
    document.getElementById("moduleHint").textContent = config.hint
    document.getElementById("searchInput").value = ""
    document.getElementById("resultsData").classList.add("hidden")
  }

  async function performSearch() {
    const input = document.getElementById("searchInput").value.trim()
    if (!input) return

    const config = moduleConfigs[currentModule]
    const loadingIndicator = document.getElementById("loadingIndicator")
    const resultsData = document.getElementById("resultsData")

    loadingIndicator.classList.remove("hidden")
    resultsData.classList.add("hidden")

    try {
      const url = `${config.endpoint}?${config.param}=${encodeURIComponent(input)}`
      const response = await fetch(url)

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        const detail = Array.isArray(err.detail) ? err.detail.map(d => d.msg).join(", ") : err.detail
        throw new Error(detail || `GHunt request failed (HTTP ${response.status})`)
      }

      currentData = await response.json()
      displayResults(currentModule, currentData)
    } catch (error) {
      console.error("Search error:", error)
      showTemporaryNotification(error.message, "error")
    } finally {
      loadingIndicator.classList.add("hidden")
    }
  }

  function displayResults(module, data) {
    // Hide all result sections
    document.querySelectorAll('#resultsData > div[id$="Results"]').forEach((section) => {
      section.classList.add("hidden")
    })

    // Show results container
    document.getElementById("resultsData").classList.remove("hidden")

    switch (module) {
      case "email":
        displayEmailResults(data)
        break
      case "gaia":
        displayGaiaResults(data)
        break
    }

    lucide.createIcons()
  }

  function displayEmailResults(data) {
    document.getElementById("emailResults").classList.remove("hidden")

    const profileContainer = data.PROFILE_CONTAINER || data
    const profile = profileContainer.profile || {}

    // Extract profile data
    const personId = profile.personId || ""
    const email = profile.emails?.PROFILE?.value || ""
    const name = profile.names?.PROFILE?.displayName || profile.names?.PROFILE?.givenName || "Unknown User"
    const profilePhoto = profile.profilePhotos?.PROFILE?.url || "/static/avatar_placeholder.png"
    const lastUpdated = profile.sourceIds?.PROFILE?.lastUpdated || ""

    // Profile Section
    document.getElementById("userAvatar").src = profilePhoto
    setElementContent("userName", name)
    setElementContent("userEmailText", email)

    if (personId) {
      showContainer("gaiaContainer", true)
      const gaiaElement = document.getElementById("gaiaId")
      gaiaElement.innerHTML = `
                <a href="https://www.google.com/maps/contrib/${personId}/reviews" target="_blank" class="text-blue-400 hover:text-blue-300 font-mono text-sm">
                    ${personId}
                    <i data-lucide="external-link" class="w-3 h-3 inline ml-1"></i>
                </a>
            `
    }

    if (lastUpdated) {
      showContainer("lastEditContainer", true)
      setElementContent("lastEdit", lastUpdated)
    }

    lucide.createIcons()
  }

  function displayGaiaResults(data) {
    document.getElementById("gaiaResults").classList.remove("hidden")

    const details = document.getElementById("gaiaDetails")
    const parts = []

    if (data.name)
      parts.push(
        `<div class="mb-3"><span class="text-gray-400 font-semibold">Name:</span> <span class="ml-2">${escapeHtml(data.name)}</span></div>`,
      )
    if (data.email)
      parts.push(`
            <div class="mb-3 flex items-center">
                <i data-lucide="mail" class="w-4 h-4 mr-2 text-gray-400"></i>
                <span class="text-gray-400 font-semibold">Email:</span> 
                <span class="ml-2">${escapeHtml(data.email)}</span>
            </div>
        `)
    if (data.gaia_id || data.personId) {
      const gaiaId = data.gaia_id || data.personId
      parts.push(`
                <div class="mb-3 flex items-center">
                    <i data-lucide="hash" class="w-4 h-4 mr-2 text-gray-400"></i>
                    <span class="text-gray-400 font-semibold">Gaia ID:</span> 
                    <a href="https://www.google.com/maps/contrib/${gaiaId}/reviews" target="_blank" class="text-blue-400 hover:text-blue-300 ml-2 font-mono text-sm">
                        ${escapeHtml(gaiaId)}
                        <i data-lucide="external-link" class="w-3 h-3 inline ml-1"></i>
                    </a>
                </div>
            `)
    }
    if (data.profile_photo)
      parts.push(
        `<img src="${escapeHtml(data.profile_photo)}" class="w-24 h-24 rounded-full mt-4 border-2 border-gray-700" alt="Profile">`,
      )

    details.innerHTML = `<div class="space-y-2">${parts.join("")}</div>`
    lucide.createIcons()
  }

  // Helper functions
  function setElementContent(id, content) {
    const element = document.getElementById(id)
    if (element) {
      element.textContent = content
    }
  }

  function showContainer(id, show) {
    const container = document.getElementById(id)
    if (container) {
      if (show) {
        container.classList.remove("hidden")
      } else {
        container.classList.add("hidden")
      }
    }
  }

  function escapeHtml(unsafe) {
    if (typeof unsafe !== "string") return ""
    return unsafe
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;")
  }
})
