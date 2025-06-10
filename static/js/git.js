document.addEventListener("DOMContentLoaded", () => {
    const lucide = window.lucide
    lucide.createIcons()

    const searchButton = document.getElementById("searchButton")
    const usernameInput = document.getElementById("usernameInput")
    const userDataDiv = document.getElementById("userData")
    const loadingIndicator = document.getElementById("loadingIndicator")

    // Add click handlers for all section toggles
    document.querySelectorAll(".section-toggle").forEach((toggle) => {
      toggle.addEventListener("click", () => {
        const sectionId = toggle.getAttribute("data-section")
        const section = document.getElementById(sectionId)
        if (!section) return

        // Toggle the section
        section.classList.toggle("expanded")

        // Toggle the icon if it exists
        const icon = toggle.querySelector("i")
        if (icon) {
          toggle.classList.toggle("active")
        }

        // Update button text if it's a repo toggle
        if (toggle.classList.contains("toggleRepos")) {
          toggle.textContent = section.classList.contains("expanded") ? "Hide repos" : "Show repos"
        }
      })
    })

    searchButton.addEventListener("click", fetchUserData)
    usernameInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") fetchUserData()
    })

    async function fetchUserData() {
      const username = usernameInput.value.trim()
      if (!username) return

      loadingIndicator.classList.remove("hidden")
      userDataDiv.classList.add("hidden")

      try {
        const response = await fetch(`/api/gitfive/query?username=${encodeURIComponent(username)}`)
        if (!response.ok) throw new Error("Failed to fetch user data")
        const data = await response.json()
        displayUserData(data)
      } catch (error) {
        console.error("Error fetching user data:", error)
        alert("Error fetching user data. Please try again.")
      } finally {
        loadingIndicator.classList.add("hidden")
      }
    }

    function formatDate(dateString) {
      return new Date(dateString).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    }

    function displayUserData(data) {
      // Update profile section
      document.getElementById("userAvatar").src = data.avatar_url
      document.getElementById("userName").textContent = data.name || data.username
      document.getElementById("userBio").textContent = data.bio || "No bio available"
      document.getElementById("repoCount").textContent = `${data.nb_public_repos} repositories`
      document.getElementById("followerCount").textContent = `${data.nb_followers} followers`
      document.getElementById("followingCount").textContent = `${data.nb_following} following`
      document.getElementById("createdAt").textContent = formatDate(data.created_at)

      // Update badges
      document.getElementById("adminBadge").classList.toggle("hidden", !data.is_site_admin)
      document.getElementById("hireableBadge").classList.toggle("hidden", !data.is_hireable)

      // Update profile links
      const blogContainer = document.getElementById("blogContainer")
      const blogLink = document.getElementById("blogLink")
      const blogUrl = document.getElementById("blogUrl")
      if (data.blog) {
        blogContainer.classList.remove("hidden")
        blogLink.href = data.blog.startsWith("http") ? data.blog : `https://${data.blog}`
        blogUrl.textContent = data.blog
      } else {
        blogContainer.classList.add("hidden")
      }

      // Update company
      const companyContainer = document.getElementById("companyContainer")
      const companyName = document.getElementById("companyName")
      if (data.company) {
        companyContainer.classList.remove("hidden")
        companyName.textContent = data.company
      } else {
        companyContainer.classList.add("hidden")
      }

      // Update location
      const locationContainer = document.getElementById("locationContainer")
      const locationName = document.getElementById("locationName")
      if (data.location) {
        locationContainer.classList.remove("hidden")
        locationName.textContent = data.location
      } else {
        locationContainer.classList.add("hidden")
      }

      // Update Twitter
      const twitterContainer = document.getElementById("twitterContainer")
      const twitterLink = document.getElementById("twitterLink")
      const twitterHandle = document.getElementById("twitterHandle")
      if (data.twitter) {
        twitterContainer.classList.remove("hidden")
        twitterLink.href = `https://twitter.com/${data.twitter}`
        twitterHandle.textContent = `@${data.twitter}`
      } else {
        twitterContainer.classList.add("hidden")
      }

      // Update language stats
      const languageStats = document.getElementById("languageStats")
      languageStats.innerHTML = Object.entries(data.languages_stats)
        .map(
          ([lang, percentage]) => `
              <div class="bg-gray-800 p-3 rounded-lg">
                  <div class="flex justify-between items-center">
                      <span class="text-sm">${lang === "null" ? "Other" : lang}</span>
                      <span class="text-sm text-gray-400">${percentage}%</span>
                  </div>
                  <div class="w-full bg-gray-700 rounded-full h-2 mt-2">
                      <div class="bg-blue-500 rounded-full h-2" style="width: ${percentage}%"></div>
                  </div>
              </div>
          `,
        )
        .join("")

      // Update repositories section
      const reposList = document.getElementById("reposList")
      reposList.innerHTML = data.repos
        .map(
          (repo) => `
              <div class="bg-gray-800 p-4 rounded-lg">
                  <div class="flex justify-between items-start">
                      <div>
                          <h4 class="font-bold">${repo.name}</h4>
                          <p class="text-gray-400 text-sm">${repo.main_language || "No language"}</p>
                      </div>
                      <div class="flex items-center space-x-4 text-sm">
                          <span class="flex items-center">
                              <i data-lucide="star" class="w-4 h-4 mr-1"></i>
                              ${repo.stars}
                          </span>
                          <span class="flex items-center">
                              <i data-lucide="git-fork" class="w-4 h-4 mr-1"></i>
                              ${repo.forks}
                          </span>
                      </div>
                  </div>
              </div>
          `,
        )
        .join("")

      // Update SSH keys section
      const sshKeysList = document.getElementById("sshKeysList")
      sshKeysList.innerHTML = data.ssh_keys
        .map(
          (key) => `
              <div class="bg-gray-800 p-3 rounded-lg">
                  <code class="text-xs break-all">${key}</code>
              </div>
          `,
        )
        .join("")

      // Update username history section
      const usernamesHistory = document.getElementById("usernamesHistory")
      usernamesHistory.innerHTML = Object.entries(data.usernames_history)
        .map(
          ([username, info]) => `
              <div class="bg-gray-800 p-4 rounded-lg">
                  <h4 class="font-bold">${username}</h4>
                  <div class="mt-2 space-y-2">
                      ${Object.entries(info.names)
                        .map(
                          ([name, nameInfo]) => `
                          <div class="text-sm">
                              <span class="text-gray-400">as "${name}" in:</span>
                              <ul class="list-disc list-inside ml-4 text-gray-300">
                                  ${nameInfo.repos.map((repo) => `<li>${repo}</li>`).join("")}
                              </ul>
                          </div>
                      `,
                        )
                        .join("")}
                  </div>
              </div>
          `,
        )
        .join("")

      // Update domains section
      const domainsList = document.getElementById("domainsList")
      domainsList.innerHTML = data.domains
        .map(
          (domain) => `
              <div class="bg-gray-800 p-3 rounded-lg">
                  <code class="text-sm">${domain}</code>
              </div>
          `,
        )
        .join("")

      // Update registered emails section
      const registeredEmailsList = document.getElementById("registeredEmailsList")
      registeredEmailsList.innerHTML = Object.entries(data.registered_emails)
        .map(
          ([email, info]) => `
              <div class="bg-gray-800 p-4 rounded-lg">
                  <div class="flex items-center justify-between">
                      <code class="text-sm">${email}</code>
                      ${
                        info.is_target
                          ? '<span class="px-2 py-0.5 text-xs bg-green-500 text-black rounded">Target User</span>'
                          : '<span class="px-2 py-0.5 text-xs bg-gray-700 rounded">Other User</span>'
                      }
                  </div>
                  <div class="mt-2 text-sm text-gray-400">
                      <div class="flex items-center mt-1">
                          <i data-lucide="user" class="w-4 h-4 mr-2"></i>
                          ${info.username}
                      </div>
                      ${
                        info.full_name
                          ? `
                          <div class="flex items-center mt-1">
                              <i data-lucide="id-card" class="w-4 h-4 mr-2"></i>
                              ${info.full_name}
                          </div>
                      `
                          : ""
                      }
                  </div>
              </div>
          `,
        )
        .join("")

      // Update all contributions section
      const allContribsList = document.getElementById("allContribsList")
      allContribsList.innerHTML = Object.entries(data.all_contribs)
        .map(
          ([email, info]) => `
              <div class="bg-gray-800 p-4 rounded-lg">
                  <div class="flex justify-between items-start">
                      <code class="text-sm">${email}</code>
                      <button class="toggleRepos bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-sm transition-colors">
                          Show repos
                      </button>
                  </div>
                  <div class="reposList mt-4 space-y-2">
                      ${Object.entries(info.names)
                        .map(
                          ([name, nameInfo]) => `
                          <div class="ml-4">
                              <div class="text-sm font-bold mb-1">as "${name}":</div>
                              <ul class="list-disc list-inside ml-4 text-sm text-gray-400">
                                  ${nameInfo.repos.map((repo) => `<li>${repo}</li>`).join("")}
                              </ul>
                          </div>
                      `,
                        )
                        .join("")}
                  </div>
              </div>
          `,
        )
        .join("")

      // Update external contributions section
      const extContribsList = document.getElementById("extContribsList")
      extContribsList.innerHTML = Object.entries(data.ext_contribs)
        .map(
          ([email, info]) => `
              <div class="bg-gray-800 p-4 rounded-lg">
                  <div class="flex justify-between items-start">
                      <code class="text-sm">${email}</code>
                      <button class="toggleRepos bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-sm transition-colors">
                          Show repos
                      </button>
                  </div>
                  <div class="reposList mt-4 space-y-2">
                      ${Object.entries(info.names)
                        .map(
                          ([name, nameInfo]) => `
                          <div class="ml-4">
                              <div class="text-sm font-bold mb-1">as "${name}":</div>
                              <ul class="list-disc list-inside ml-4 text-sm text-gray-400">
                                  ${nameInfo.repos.map((repo) => `<li>${repo}</li>`).join("")}
                              </ul>
                          </div>
                      `,
                        )
                        .join("")}
                  </div>
              </div>
          `,
        )
        .join("")

      // Update near names section
      const nearNamesList = document.getElementById("nearNamesList")
      nearNamesList.innerHTML = Object.entries(data.near_names)
        .map(
          ([name, info]) => `
              <div class="bg-gray-800 p-4 rounded-lg">
                  <h4 class="font-bold">${name}</h4>
                  <div class="mt-2 space-y-2">
                      ${Object.entries(info.related_data)
                        .map(
                          ([email, emailInfo]) => `
                          <div>
                              <code class="text-sm">${email}</code>
                              <div class="mt-2 text-sm text-gray-400"></div>
                              <div class="mt-2">
                                  ${Object.entries(emailInfo.names)
                                    .map(
                                      ([userName, userInfo]) => `
                                      <div class="ml-4">
                                          <div class="text-sm font-bold mb-1">as "${userName}":</div>
                                          <ul class="list-disc list-inside ml-4 text-sm text-gray-400">
                                              ${userInfo.repos.map((repo) => `<li>${repo}</li>`).join("")}
                                          </ul>
                                      </div>
                                  `,
                                    )
                                    .join("")}
                              </div>
                          </div>
                      `,
                        )
                        .join("")}
                  </div>
              </div>
          `,
        )
        .join("")

      // Show results
      userDataDiv.classList.remove("hidden")

      // Reinitialize Lucide icons for new content
      lucide.createIcons()

      // Add event listeners for repo toggles
      document.querySelectorAll(".toggleRepos").forEach((button) => {
        button.addEventListener("click", (e) => {
          const reposList = e.target.closest("div.bg-gray-800").querySelector(".reposList")
          reposList.classList.toggle("expanded")
          e.target.textContent = reposList.classList.contains("expanded") ? "Hide repos" : "Show repos"
        })
      })
    }
  })

