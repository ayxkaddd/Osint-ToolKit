// lookup.js - universal search: detect what the query is, offer the modules
// that can look it up (cost/speed/readiness/earlier runs), run them as jobs.

const lookupEls = {
  form: document.getElementById("lookupForm"),
  query: document.getElementById("lookupQuery"),
  investigation: document.getElementById("lookupInvestigation"),
  candidates: document.getElementById("lookupCandidates"),
  runBar: document.getElementById("lookupRunBar"),
  runSummary: document.getElementById("lookupRunSummary"),
  runButton: document.getElementById("lookupRunButton"),
  jobsSection: document.getElementById("lookupJobsSection"),
  jobs: document.getElementById("lookupJobs"),
}
const startedHere = new Set()
let lastDetection = null

function selectedLookups() {
  return Array.from(lookupEls.candidates.querySelectorAll("input[data-module]:checked")).map((box) => ({
    module: box.dataset.module,
    type: box.dataset.type,
    value: box.dataset.value,
    paid: box.dataset.paid === "true",
  }))
}

function updateRunBar() {
  const picks = selectedLookups()
  const paid = picks.filter((p) => p.paid).length
  lookupEls.runBar.classList.toggle("hidden", !lastDetection || !lastDetection.candidates.length)
  lookupEls.runSummary.textContent = picks.length
    ? `${picks.length} lookup${picks.length > 1 ? "s" : ""} selected${paid ? ` · ${paid} use paid credits` : ""}`
    : "Select the modules to run"
  lookupEls.runButton.disabled = !picks.length
  lookupEls.runButton.textContent = picks.length ? `Run ${picks.length}` : "Run"
}

function renderInvestigationBanner(investigationId) {
  if (investigationId) {
    lookupEls.investigation.innerHTML = `<span class="text-gray-400"><span class="rec-dot mr-1.5"></span>Results are saved to the current investigation.</span>
      <a href="/api/investigations/${escapeAttr(investigationId)}/view" class="text-purple-300 hover:text-white ml-2">Open it</a>`
  } else {
    lookupEls.investigation.innerHTML = `
      <div class="bg-yellow-900/30 border border-yellow-700/60 rounded-lg px-4 py-3 flex items-center justify-between gap-3">
        <span class="text-yellow-100">Lookups are saved to an investigation. Select one in the header, or create one.</span>
        <button type="button" onclick="openCreateModal()" class="bg-yellow-700/60 hover:bg-yellow-600/60 px-3 py-1.5 rounded text-sm shrink-0">New investigation</button>
      </div>`
  }
}

function moduleRow(candidate, m) {
  const previous = m.previous || []
  const last = previous[previous.length - 1]
  // Free ready modules default on; paid ones only if not already run in this case
  const checked = m.ready && (m.cost !== "paid" || !last)
  const lastLink = last && last.result_id && m.page
    ? `${m.page}?load_result=${encodeURIComponent(last.result_id)}&investigation=${encodeURIComponent(lastDetection.investigation_id || "")}`
    : null
  return `
    <label class="flex items-start gap-3 p-3 rounded-lg border ${m.ready ? "border-gray-800 hover:border-purple-500/40 cursor-pointer" : "border-gray-800/60 opacity-60"} bg-gray-900/60">
        <input type="checkbox" class="mt-1 pick-box"
            data-module="${escapeAttr(m.id)}" data-type="${escapeAttr(candidate.type)}" data-value="${escapeAttr(candidate.value)}"
            data-paid="${m.cost === "paid"}" ${checked ? "checked" : ""} ${m.ready ? "" : "disabled"}>
        <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 flex-wrap">
                <span class="font-medium text-white">${escapeHtml(m.name)}</span>
                ${moduleBadges(m)}
            </div>
            ${m.cost_note ? `<div class="text-xs text-gray-500">${escapeHtml(m.cost_note)}</div>` : ""}
            ${m.ready ? "" : `<div class="text-xs text-red-300 mt-0.5">${escapeHtml((m.problems || []).join("; "))} <a href="/settings" class="underline">Settings</a></div>`}
            ${last ? `<div class="text-xs text-amber-300 mt-0.5"><i class="fas fa-history mr-1"></i>Already looked up ${escapeHtml(timeAgo(last.timestamp))}${lastLink ? ` · <a href="${escapeAttr(lastLink)}" class="underline">open result</a>` : ""}</div>` : ""}
        </div>
    </label>`
}

function renderCandidates(data) {
  lastDetection = data
  renderInvestigationBanner(data.investigation_id)
  if (!data.candidates.length) {
    lookupEls.candidates.innerHTML = '<p class="text-gray-400">Couldn\'t recognise this - try an email, phone with country code, @username, domain or IP.</p>'
    updateRunBar()
    return
  }
  lookupEls.candidates.innerHTML = data.candidates.map((c, i) => `
    <section class="bg-[#14151f] border border-[#24283b] rounded-xl p-5">
        <div class="flex items-baseline justify-between gap-3 mb-3 flex-wrap">
            <div>
                <span class="text-xs uppercase tracking-wider text-gray-500">${i === 0 ? "Looks like" : "Could also be"} · ${escapeHtml(c.label)}</span>
                <div class="font-mono text-lg text-purple-200 break-all">${escapeHtml(c.display || c.value)}</div>
            </div>
            <div class="text-xs flex gap-3">
                <button type="button" data-select-all="${i}" class="text-gray-400 hover:text-white">Select all ready</button>
                <button type="button" data-select-none="${i}" class="text-gray-400 hover:text-white">None</button>
            </div>
        </div>
        ${c.modules.length
          ? `<div class="grid grid-cols-1 md:grid-cols-2 gap-2" data-candidate="${i}">${c.modules.map((m) => moduleRow(c, m)).join("")}</div>`
          : '<p class="text-sm text-gray-500">No module looks this type up yet.</p>'}
    </section>`).join("")
  // Only the first reading is pre-selected; other readings are opt-in
  lookupEls.candidates.querySelectorAll("[data-candidate]").forEach((grid) => {
    if (grid.dataset.candidate !== "0") grid.querySelectorAll("input:checked").forEach((box) => { box.checked = false })
  })
  updateRunBar()
}

async function analyze(query) {
  query = (query || "").trim()
  if (!query) return
  history.replaceState(null, "", `/lookup?q=${encodeURIComponent(query)}`)
  lookupEls.candidates.innerHTML = '<p class="text-gray-400"><i class="fas fa-spinner fa-spin mr-2"></i>Analyzing…</p>'
  try {
    const response = await fetch(`/api/lookup/detect?q=${encodeURIComponent(query)}`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
    renderCandidates(data)
  } catch (error) {
    lookupEls.candidates.innerHTML = `<p class="text-red-400">${escapeHtml(error.message)}</p>`
  }
}

function renderStartedJobs(jobs) {
  const mine = jobs.filter((j) => startedHere.has(j.id))
  lookupEls.jobsSection.classList.toggle("hidden", mine.length === 0)
  lookupEls.jobs.innerHTML = mine.map((job) => {
    const link = jobResultLink(job)
    return `
      <div class="bg-gray-900/70 border border-gray-800 rounded-lg px-4 py-3 flex items-center justify-between gap-4">
          <div class="min-w-0">
              <div class="text-white">${escapeHtml(job.module_name)} <span class="font-mono text-purple-200 text-sm">${escapeHtml(job.value)}</span></div>
              <div class="text-xs mt-0.5">${jobStatusHtml(job)}</div>
          </div>
          <div class="flex gap-3 text-sm shrink-0">
              ${job.status === "running" || job.status === "queued" ? `<button type="button" data-job-cancel="${escapeAttr(job.id)}" class="text-gray-400 hover:text-red-300">Cancel</button>` : ""}
              ${link ? `<a href="${escapeAttr(link)}" class="text-purple-300 hover:text-white">Open result</a>` : ""}
          </div>
      </div>`
  }).join("")
}

lookupEls.form.addEventListener("submit", (e) => {
  e.preventDefault()
  analyze(lookupEls.query.value)
})

lookupEls.candidates.addEventListener("change", updateRunBar)
lookupEls.candidates.addEventListener("click", (e) => {
  const all = e.target.closest("[data-select-all]")
  const none = e.target.closest("[data-select-none]")
  const index = (all || none)?.dataset.selectAll ?? (all || none)?.dataset.selectNone
  if (index === undefined) return
  lookupEls.candidates.querySelectorAll(`[data-candidate="${index}"] input[data-module]`).forEach((box) => {
    if (!box.disabled) box.checked = Boolean(all)
  })
  updateRunBar()
})

lookupEls.runButton.addEventListener("click", async () => {
  const picks = selectedLookups()
  if (!picks.length) return
  if (!lastDetection.investigation_id) {
    showTemporaryNotification("Select or create an investigation first", "error")
    return
  }
  lookupEls.runButton.disabled = true
  for (const pick of picks) {
    const job = await startJob(pick.module, pick.type, pick.value)
    if (job) startedHere.add(job.id)
  }
  lookupEls.candidates.querySelectorAll("input[data-module]:checked").forEach((box) => { box.checked = false })
  updateRunBar()
  lookupEls.jobsSection.scrollIntoView({ behavior: "smooth", block: "start" })
})

document.addEventListener("jobs:updated", (e) => renderStartedJobs(e.detail))
document.addEventListener("investigation:changed", () => lastDetection && analyze(lastDetection.query))

const initialQuery = new URLSearchParams(window.location.search).get("q")
if (initialQuery) {
  lookupEls.query.value = initialQuery
  analyze(initialQuery)
}
