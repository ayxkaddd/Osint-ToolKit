// Runs in the header, before the first paint (base.html): the last known name of the
// current investigation; main.js corrects it from the server
try {
    const name = localStorage.getItem('currentInvestigationName');
    if (name && localStorage.getItem('currentInvestigationId')) {
        const label = document.getElementById('currentInvestigationName');
        label.textContent = name;
        label.classList.add('text-purple-300');
        document.getElementById('investigationsDropdown').classList.add('recording');
    }
} catch (e) {}
