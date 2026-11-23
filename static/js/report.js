// Case report (report.html). Only works when the report is opened from the server;
// a saved copy still prints with the browser's own print command.
document.getElementById('printReport')?.addEventListener('click', () => window.print());
