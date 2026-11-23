// Login page (index.html)
const loginForm = document.getElementById('loginForm');
const loginButton = document.getElementById('loginButton');

function showError(message) {
    document.getElementById('errorText').textContent = message;
    document.getElementById('errorMessage').classList.remove('hidden');
}

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    document.getElementById('errorMessage').classList.add('hidden');
    loginButton.disabled = true;
    try {
        const response = await fetch('/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: document.getElementById('email').value,
                password: document.getElementById('password').value,
            }),
            credentials: 'include',
        });
        const data = await response.json().catch(() => ({}));
        if (response.ok && data.success) {
            window.location.href = '/dashboard';
            return;
        }
        showError(
            response.status === 429 ? 'Too many attempts - wait a minute and try again.' : 'Wrong email or password.'
        );
    } catch (error) {
        showError('Could not reach the server.');
    } finally {
        loginButton.disabled = false;
    }
});
