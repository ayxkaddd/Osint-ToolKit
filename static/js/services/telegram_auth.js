lucide.createIcons();
let currentPhoneNumber = null;

function showStatus(message, isError = false) {
    const statusEl = document.getElementById('status');
    statusEl.classList.remove('hidden', 'bg-red-800', 'bg-gray-800');
    statusEl.classList.add(isError ? 'bg-red-800' : 'bg-gray-800');
    statusEl.innerHTML = `
        <div class="flex items-center justify-center gap-2">
            ${isError ? '<i data-lucide="alert-circle"></i>' : '<i data-lucide="info"></i>'}
            <span>${message}</span>
        </div>
    `;
    lucide.createIcons();
}

function showError(message) {
    const errorEl = document.getElementById('error');
    errorEl.classList.remove('hidden');
    errorEl.textContent = message;
    setTimeout(() => errorEl.classList.add('hidden'), 3000);
}

async function checkAuth() {
    try {
        const response = await fetch('/auth/tg/status');
        const { authorized, configured } = await response.json();

        if (configured === false) {
            showStatus('Telegram API ID and hash are not set. Add them under VK Profile History in <a href="/settings" class="underline">Settings</a>, then come back here to log in.');
            document.getElementById('phoneForm').classList.add('hidden');
        } else if (authorized) {
            showStatus("✅ Authenticated successfully!");
            document.getElementById('phoneForm').classList.add('hidden');
            document.getElementById('codeForm').classList.add('hidden');
        } else {
            showStatus("🔒 Please authenticate with Telegram");
            document.getElementById('phoneForm').classList.remove('hidden');
        }
    } catch (error) {
        showError("Failed to check authentication status");
    }
}

async function handlePhoneSubmit(e) {
    e.preventDefault();
    currentPhoneNumber = document.getElementById('phone').value;

    try {
        const response = await fetch('/auth/tg/request-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone_number: currentPhoneNumber })
        });

        if (response.ok) {
            document.getElementById('phoneForm').classList.add('hidden');
            document.getElementById('codeForm').classList.remove('hidden');
            showStatus("📲 Verification code sent to your Telegram");
        } else {
            const error = await response.json();
            showError(error.detail);
        }
    } catch (error) {
        showError("Failed to send verification code");
    }
}

async function handleCodeSubmit(e) {
    e.preventDefault();
    const code = document.getElementById('code').value;

    try {
        const response = await fetch('/auth/tg/verify-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                phone_number: currentPhoneNumber,
                code: code
            })
        });

        if (response.ok) {
            const result = await response.json();
            if (result.status === 'password_required') {
                codeForm.classList.add('hidden');
                passwordForm.classList.remove('hidden');
                document.getElementById('tgPassword').focus();
                return;
            }
            await checkAuth();
        } else {
            const error = await response.json();
            showError(error.detail);
        }
    } catch (error) {
        showError("Failed to verify code");
    }
}

async function handlePasswordSubmit(e) {
    e.preventDefault();
    const password = document.getElementById('tgPassword').value;
    try {
        const response = await fetch('/auth/tg/verify-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
        });
        if (response.ok) {
            passwordForm.classList.add('hidden');
            await checkAuth();
        } else {
            const error = await response.json();
            showError(error.detail);
        }
    } catch (error) {
        showError("Failed to verify password");
    }
}

const phoneForm = document.getElementById('phoneForm');
const codeForm = document.getElementById('codeForm');
const passwordForm = document.getElementById('passwordForm');

if (phoneForm) {
    phoneForm.addEventListener('submit', handlePhoneSubmit);
}
if (codeForm) {
    codeForm.addEventListener('submit', handleCodeSubmit);
}
if (passwordForm) {
    passwordForm.addEventListener('submit', handlePasswordSubmit);
}

checkAuth();
