// Background lookups (the jobs tray).
import { escapeAttr, escapeHtml, showTemporaryNotification, timeAgo } from './dom.js';

// ---------------------------------------------------------------------------
// Background jobs
// ---------------------------------------------------------------------------
let jobPollTimer = null;

let jobStatusSeen = null; // job id -> status (null until the first fetch)

export async function startJob(moduleId, type, value, parentResultId = null) {
    try {
        const response = await fetch('/api/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ module: moduleId, type, value, parent_result_id: parentResultId }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        showTemporaryNotification(`Started ${data.job.module_name} on ${value}`, 'info');
        refreshJobs();
        document.dispatchEvent(new CustomEvent('jobs:started', { detail: data.job }));
        return data.job;
    } catch (error) {
        showTemporaryNotification(error.message, 'error');
        return null;
    }
}

export function jobResultLink(job) {
    if (!job.result_id || !job.module_page) return null;
    return `${job.module_page}?load_result=${encodeURIComponent(job.result_id)}&investigation=${encodeURIComponent(job.investigation_id)}`;
}

export function jobStatusHtml(job) {
    const p = job.progress || {};
    if (job.status === 'running') {
        const count = p.total ? `${p.done || 0}/${p.total}` : p.done ? `${p.done}` : '';
        return `<span class="text-blue-300"><i class="fas fa-spinner fa-spin mr-1"></i>running ${escapeHtml(count)}${p.found ? ` · ${escapeHtml(p.found)} found` : ''}</span>`;
    }
    if (job.status === 'queued') return '<span class="text-gray-400"><i class="fas fa-clock mr-1"></i>queued</span>';
    if (job.status === 'done')
        return `<span class="text-emerald-300"><i class="fas fa-check mr-1"></i>${escapeHtml(job.summary || 'done')}</span>`;
    if (job.status === 'cancelled')
        return '<span class="text-gray-400"><i class="fas fa-ban mr-1"></i>cancelled</span>';
    return `<span class="text-red-300" title="${escapeAttr(job.error || '')}"><i class="fas fa-exclamation-triangle mr-1"></i>${escapeHtml((job.error || 'failed').slice(0, 90))}</span>`;
}

function renderJobsTray(jobs) {
    const list = document.getElementById('jobsTrayList');
    const count = document.getElementById('jobsTrayCount');
    if (!list || !count) return;
    const active = jobs.filter((j) => j.status === 'running' || j.status === 'queued').length;
    count.textContent = active;
    count.classList.toggle('hidden', active === 0);
    if (!jobs.length) {
        list.innerHTML = '<div class="p-4 text-center text-gray-500">No lookups yet</div>';
        return;
    }
    list.innerHTML = jobs
        .slice(0, 25)
        .map((job) => {
            const link = jobResultLink(job);
            return `
        <div class="px-4 py-2.5 border-b border-gray-800 last:border-0">
            <div class="flex justify-between gap-2">
                <span class="font-medium text-white truncate">${escapeHtml(job.module_name)}</span>
                <span class="text-xs text-gray-500 shrink-0">${escapeHtml(timeAgo(job.created_at))}</span>
            </div>
            <div class="font-mono text-xs text-purple-200 truncate">${escapeHtml(job.value)}</div>
            <div class="flex justify-between items-center gap-2 mt-1 text-xs">
                <div class="min-w-0 truncate">${jobStatusHtml(job)}</div>
                <div class="shrink-0 flex gap-3">
                    ${job.status === 'running' || job.status === 'queued' ? `<button type="button" data-job-cancel="${escapeAttr(job.id)}" class="text-gray-400 hover:text-red-300">Cancel</button>` : ''}
                    ${link ? `<a href="${escapeAttr(link)}" class="text-purple-300 hover:text-white">Open</a>` : ''}
                </div>
            </div>
        </div>`;
        })
        .join('');
}

export async function refreshJobs() {
    let jobs = [];
    try {
        const response = await fetch('/api/jobs?limit=30');
        if (!response.ok) return;
        jobs = (await response.json()).jobs || [];
    } catch (e) {
        return;
    }
    // Notify about lookups that finished while this page was open
    if (jobStatusSeen) {
        jobs.forEach((job) => {
            const before = jobStatusSeen[job.id];
            if ((before === 'running' || before === 'queued') && job.status !== before) {
                if (job.status === 'done')
                    showTemporaryNotification(`${job.module_name} finished: ${job.summary || 'done'}`, 'success');
                if (job.status === 'failed')
                    showTemporaryNotification(`${job.module_name} failed: ${job.error || ''}`, 'error');
            }
        });
    }
    jobStatusSeen = Object.fromEntries(jobs.map((j) => [j.id, j.status]));
    renderJobsTray(jobs);
    document.dispatchEvent(new CustomEvent('jobs:updated', { detail: jobs }));

    const active = jobs.some((j) => j.status === 'running' || j.status === 'queued');
    clearTimeout(jobPollTimer);
    if (active) jobPollTimer = setTimeout(refreshJobs, 2000);
}

document.addEventListener('click', async (event) => {
    if (event.target.closest('#jobsTrayButton')) {
        document.getElementById('jobsTrayMenu')?.classList.toggle('hidden');
        refreshJobs();
        return;
    }
    const cancel = event.target.closest('[data-job-cancel]');
    if (cancel) {
        await fetch(`/api/jobs/${encodeURIComponent(cancel.dataset.jobCancel)}`, { method: 'DELETE' });
        refreshJobs();
        return;
    }
    const menu = document.getElementById('jobsTrayMenu');
    if (menu && !menu.classList.contains('hidden') && !event.target.closest('#jobsTrayMenu'))
        menu.classList.add('hidden');
});

document.addEventListener('jobs:started', () => refreshJobs());
