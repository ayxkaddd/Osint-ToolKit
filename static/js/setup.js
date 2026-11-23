// Setup wizard steps (setup.html); the step HTML is in setup-advanced.js
let currentStep = 1;
const { system_status: systemStatus, step: initialStep } = pageData('setupData');

// Password validation
document.getElementById('password')?.addEventListener('input', function (e) {
    const pwd = e.target.value;
    document.getElementById('req-length').textContent = pwd.length >= 8 ? '✓' : '✗';
    document.getElementById('req-length').className = pwd.length >= 8 ? 'text-green-400' : 'text-red-400';
    document.getElementById('req-upper').textContent = /[A-Z]/.test(pwd) ? '✓' : '✗';
    document.getElementById('req-upper').className = /[A-Z]/.test(pwd) ? 'text-green-400' : 'text-red-400';
    document.getElementById('req-lower').textContent = /[a-z]/.test(pwd) ? '✓' : '✗';
    document.getElementById('req-lower').className = /[a-z]/.test(pwd) ? 'text-green-400' : 'text-red-400';
    document.getElementById('req-digit').textContent = /\d/.test(pwd) ? '✓' : '✗';
    document.getElementById('req-digit').className = /\d/.test(pwd) ? 'text-green-400' : 'text-red-400';
});

function showStep(step) {
    document.querySelectorAll('.setup-step').forEach((el) => el.classList.add('hidden'));
    const stepEl = document.getElementById(`step-${step}`);
    if (stepEl) stepEl.classList.remove('hidden');

    for (let i = 1; i <= 5; i++) {
        const indicator = document.getElementById(`step-${i}-indicator`);
        if (i < step) {
            indicator.classList.add('completed');
            indicator.classList.remove('active');
            indicator.innerHTML = '<i data-lucide="check" class="w-4 h-4"></i>';
        } else if (i === step) {
            indicator.classList.add('active');
            indicator.classList.remove('completed');
            indicator.textContent = i;
        } else {
            indicator.classList.remove('active', 'completed');
            indicator.textContent = i;
        }
        if (i < 5) {
            const line = document.getElementById(`line-${i}`);
            line.className = i < step ? 'flex-1 h-1 bg-green-500 mx-2' : 'flex-1 h-1 bg-gray-800 mx-2';
        }
    }
    currentStep = step;
    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Load step content dynamically
    loadStepContent(step);
}

function loadStepContent(step) {
    const container = document.getElementById('dynamic-steps');
    if (step === 2) {
        container.innerHTML = getStep2HTML();
    } else if (step === 3) {
        container.innerHTML = getStep3HTML();
        checkGoTools();
    } else if (step === 4) {
        container.innerHTML = getStep4HTML();
    } else if (step === 5) {
        container.innerHTML = getStep5HTML();
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function nextStep() {
    if (currentStep < 5) showStep(currentStep + 1);
}

function previousStep() {
    if (currentStep > 1) showStep(currentStep - 1);
}

function showLoading(show, text = 'Processing...') {
    document.getElementById('loading-overlay').classList.toggle('hidden', !show);
    document.getElementById('loading-text').textContent = text;
}

function showNotification(message, type = 'info') {
    const colors = {
        success: 'bg-green-600 border-green-600',
        error: 'bg-red-600 border-red-600',
        info: 'bg-gray-700 border-gray-600',
    };
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 ${colors[type]} border text-white px-6 py-3 rounded-lg shadow-lg z-50`;
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => notification.remove(), 3000);
}

// Admin form handler
document.getElementById('admin-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    if (formData.get('password') !== formData.get('confirm_password')) {
        showNotification('Passwords do not match', 'error');
        return;
    }
    showLoading(true, 'Configuring admin account...');
    try {
        const response = await fetch('/setup/admin', { method: 'POST', body: formData });
        const data = await response.json();
        if (data.success) {
            showNotification('Admin configured successfully', 'success');
            nextStep();
        } else {
            showNotification(data.detail || 'Configuration failed', 'error');
        }
    } catch (error) {
        showNotification('Error: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
});

document.addEventListener('DOMContentLoaded', () => {
    showStep(initialStep);
});

registerActions({
    nextStep,
    previousStep,
    refreshSystemStatus,
    installGoTools,
    showGitFiveGuide,
    validateKey,
    completeSetup,
});
