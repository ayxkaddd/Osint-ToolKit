// The image viewer, on every page.
import { escapeAttr, escapeHtml, safeUrl } from './dom.js';

// ---------------------------------------------------------------------------
// Image viewer, on every page. Elements with data-image-view open it on click: the
// attribute holds the full image's URL, or stays empty to show the <img> itself.
// Optional: data-image-title, data-image-note.
// ---------------------------------------------------------------------------
export function openImageViewer(url, title = 'Image', note = 'Image preview') {
    if (!url) return;
    const modal = document.createElement('div');
    modal.className = 'modal-overlay username-image-preview-overlay';
    const original = safeUrl(url);
    modal.innerHTML = `
    <div class="username-image-preview-card">
        <div class="username-image-preview-header">
            <div class="min-w-0">
                <h2 class="truncate">${escapeHtml(title)}</h2>
                <p>${escapeHtml(note)}</p>
            </div>
            <div class="flex gap-2 shrink-0">
                ${original ? `<a href="${escapeAttr(original)}" target="_blank" rel="noopener noreferrer" title="Open the original in a new tab"><i class="fas fa-external-link-alt"></i></a>` : ''}
                <button type="button" class="close-modal" title="Close preview"><i class="fas fa-times"></i></button>
            </div>
        </div>
        <div class="username-image-preview-body">
            <img alt="" referrerpolicy="no-referrer">
        </div>
    </div>`;
    const image = modal.querySelector('img');
    image.onerror = () => {
        image.parentElement.innerHTML = '<span>Image could not be loaded.</span>';
    };
    image.src = url;

    const close = () => {
        modal.remove();
        document.removeEventListener('keydown', onKey, true);
    };
    // Capture: Esc closes only the viewer, not a window underneath it
    const onKey = (event) => {
        if (event.key !== 'Escape') return;
        event.stopPropagation();
        close();
    };
    document.addEventListener('keydown', onKey, true);
    modal.addEventListener('click', (event) => {
        if (event.target === modal) close();
    });
    modal.querySelector('.close-modal').addEventListener('click', close);
    document.body.appendChild(modal);
}

// Capture: opening an image must not also open or toggle the card it sits in.
// Images in notes come from the editor bundle, so they are matched by class.
document.addEventListener(
    'click',
    (event) => {
        const trigger = event.target.closest('[data-image-view], img.cm-md-image');
        if (!trigger) return;
        event.preventDefault();
        event.stopPropagation();
        const url = trigger.dataset.imageView || trigger.currentSrc || trigger.src;
        openImageViewer(url, trigger.dataset.imageTitle || trigger.alt || 'Image', trigger.dataset.imageNote);
    },
    true
);
