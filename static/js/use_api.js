async function updateCredits() {
    try {
        const response = await fetch('/api/oi/credits');
        const data = await response.json();
        document.getElementById('credits').textContent = `Available Credits: ${data.credits}`;
    } catch (error) {
        document.getElementById('credits').textContent = 'Error loading credits';
    }
}

updateCredits();

document.getElementById('submitQuery').addEventListener('click', async () => {
    const type = document.getElementById('queryType').value;
    const query = document.getElementById('queryInput').value;

    if (!query.trim()) {
        alert('Please enter a query');
        return;
    }

    const loading = document.getElementById('loading');
    const result = document.getElementById('result');
    const resultContent = document.getElementById('resultContent');
    const pdfDownload = document.getElementById('pdfDownload');
    const pdfLink = document.getElementById('pdfLink');

    loading.classList.remove('hidden');
    result.classList.add('hidden');

    try {
        const response = await fetch(`/api/oi/query?type=${encodeURIComponent(type).toLowerCase()}&query=${encodeURIComponent(query)}`);
        const data = await response.json();

        if (data.url) {
            pdfLink.href = data.url;
            pdfDownload.classList.remove('hidden');
            resultContent.textContent = 'PDF report generated successfully';
        } else {
            pdfDownload.classList.add('hidden');
            resultContent.textContent = JSON.stringify(data, null, 2);
        }

        result.classList.remove('hidden');
        await updateCredits();
    } catch (error) {
        resultContent.textContent = 'Error: ' + error.message;
        result.classList.remove('hidden');
        pdfDownload.classList.add('hidden');
    } finally {
        loading.classList.add('hidden');
    }
});

// Initialize Lucide icons
lucide.createIcons();

// Add active state handling for query type buttons
const queryTypeBtns = document.querySelectorAll('.query-type-btn');
const queryTypeInput = document.getElementById('queryType');
const queryInput = document.getElementById('queryInput');

// Set initial active state
queryTypeBtns[0].classList.add('bg-blue-600', 'hover:bg-blue-700');

queryTypeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        // Remove active state from all buttons
        queryTypeBtns.forEach(b => {
            b.classList.remove('bg-blue-600', 'hover:bg-blue-700');
            b.classList.add('bg-gray-800', 'hover:bg-gray-700');
        });

        // Add active state to clicked button
        btn.classList.remove('bg-gray-800', 'hover:bg-gray-700');
        btn.classList.add('bg-blue-600', 'hover:bg-blue-700');

        // Update hidden input value
        queryTypeInput.value = btn.dataset.type;

        // Update placeholder text
        queryInput.placeholder = `Enter ${btn.dataset.type}...`;
    });
});