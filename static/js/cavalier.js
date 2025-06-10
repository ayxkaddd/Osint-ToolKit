function formatDateNew(dateString) {
    const date = new Date(dateString);
    const day = date.getUTCDate().toString().padStart(2, "0");
    const month = date.toLocaleString("en-US", {
        month: "short",
        timeZone: "UTC",
    });
    const year = date.getUTCFullYear();
    const hour = date.getUTCHours().toString().padStart(2, "0");
    const minute = date.getUTCMinutes().toString().padStart(2, "0");

    return `${day} ${month}, ${year} ${hour}:${minute} +01:00`;
}

function isEmail(input) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(input);
}

async function fetchStealerData(input) {
    const isEmailCheck = isEmail(input);
    let cavalierUrl;

    if (isEmailCheck) {
        cavalierUrl = `https://cavalier.hudsonrock.com/api/json/v2/preview/search-by-login/osint-tools?email=${encodeURIComponent(input)}`;
    } else {
        cavalierUrl = `https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-username?username=${encodeURIComponent(input)}`;
    }

    const proxyUrl = `https://api.allorigins.win/raw?url=${encodeURIComponent(cavalierUrl)}`;
    const response = await fetch(proxyUrl);

    if (!response.ok) {
        if (response.status === 500) return { error: "not found" };
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return await response.json();
}

function createStealerCard(data, isEmailSearch) {
    const card = document.createElement("div");
    card.className = "bg-gray-900 rounded-lg p-6 border border-gray-700";

    const title = document.createElement("h2");
    title.className = "text-xl font-bold text-white mb-4 flex items-center gap-2";
    title.innerHTML = '<i class="fas fa-shield-virus text-blue-500"></i>Cavalier Information';

    const content = document.createElement("div");
    content.className = "space-y-4";

    if (data.error === "not found") {
        content.innerHTML = '<p class="text-gray-400">No information found.</p>';
        card.appendChild(title);
        card.appendChild(content);
        return card;
    }

    if (isEmailSearch) {
        if (data.data?.length > 0) {
            data.data.forEach((entry, index) => {
                content.innerHTML += `
                    ${index > 0 ? '<hr class="my-4">' : ''}
                    <p><i class="fas fa-calendar-alt stealer-icon"></i><span class="stealer-label">Date Compromised:</span>
                    <span class="stealer-value">${formatDateNew(entry.date_compromised)}</span></p>
                    <p><i class="fas fa-bug stealer-icon"></i><span class="stealer-label">Stealer Family:</span>
                    <span class="stealer-value">${entry.stealer || '••••••••••••••••••••'}</span></p>
                    <p><i class="fas fa-desktop stealer-icon"></i><span class="stealer-label">Computer Name:</span>
                    <span class="stealer-value">${entry.computer_name}</span></p>
                    <p><i class="fab fa-windows stealer-icon"></i><span class="stealer-label">Operating System:</span>
                    <span class="stealer-value">${entry.operating_system}</span></p>
                    <p><i class="fas fa-file-code stealer-icon"></i><span class="stealer-label">Malware Path:</span>
                    <span class="stealer-value">${entry.malware_path}</span></p>
                    <p><i class="fas fa-shield-alt stealer-icon"></i><span class="stealer-label">Antiviruses:</span>
                    <span class="stealer-value">${Array.isArray(entry.antiviruses) ? entry.antiviruses.join(", ") : entry.antiviruses}</span></p>
                    <p><i class="fas fa-network-wired stealer-icon"></i><span class="stealer-label">IP:</span>
                    <span class="stealer-value">${entry.ip}</span></p>
                    ${entry.clientAt ? `<p><i class="fas fa-users stealer-icon"></i><span class="stealer-label">Client At:</span>
                        <span class="stealer-value">${entry.clientAt.filter(e => e).join(", ")}</span></p>` : ''}
                    ${entry.credentials?.length > 0 ? `
                    <div class="mt-4">
                        <p class="stealer-label"><i class="fas fa-key stealer-icon"></i>Credentials:</p>
                        <div class="credentials-grid">
                            ${entry.credentials.map(cred => `
                                <div class="credential-line">
                                    <span class="cred-domain">${cred.domain}</span>
                                    <span class="cred-username">${cred.username}</span>
                                    <span class="cred-password">${cred.password ? '••••••••••' : ''}</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                    ` : ''}
                `;
            });
        }
    } else {
        if (!data.stealers || data.stealers.length === 0) {
            content.innerHTML = '<p class="stealer-value">No stealer details available.</p>';
        } else {
            data.stealers.forEach((stealer, index) => {
                content.innerHTML += `
                    ${index > 0 ? '<hr class="my-4">' : ''}
                    <p><i class="fas fa-calendar-alt stealer-icon"></i><span class="stealer-label">Date Compromised:</span>
                    <span class="stealer-value">${formatDateNew(stealer.date_compromised)}</span></p>
                    <p><i class="fas fa-bug stealer-icon"></i><span class="stealer-label">Stealer Family:</span>
                    <span class="stealer-value">${stealer.stealer_family}</span></p>
                    <p><i class="fas fa-desktop stealer-icon"></i><span class="stealer-label">Computer Name:</span>
                    <span class="stealer-value">${stealer.computer_name}</span></p>
                    <p><i class="fab fa-windows stealer-icon"></i><span class="stealer-label">Operating System:</span>
                    <span class="stealer-value">${stealer.operating_system}</span></p>
                    <p><i class="fas fa-file-code stealer-icon"></i><span class="stealer-label">Malware Path:</span>
                    <span class="stealer-value">${stealer.malware_path}</span></p>
                    <p><i class="fas fa-shield-alt stealer-icon"></i><span class="stealer-label">Antiviruses:</span>
                    <span class="stealer-value">${Array.isArray(stealer.antiviruses) ? stealer.antiviruses.join(", ") : stealer.antiviruses}</span></p>
                    <p><i class="fas fa-network-wired stealer-icon"></i><span class="stealer-label">IP:</span>
                    <span class="stealer-value">${stealer.ip}</span></p>
                    <p><i class="fas fa-key stealer-icon"></i><span class="stealer-label">Top Passwords:</span>
                    <ul class="stealer-list">
                        ${stealer.top_passwords.map((pwd) => `<li>${pwd}</li>`).join("")}
                    </ul></p>
                    <p><i class="fas fa-user stealer-icon"></i><span class="stealer-label">Top Logins:</span>
                    <ul class="stealer-list">
                        ${stealer.top_logins.map((login) => `<li>${login}</li>`).join("")}
                    </ul></p>
                `;
            });
        }
    }

    card.appendChild(title);
    card.appendChild(content);
    return card;
}

async function displayResults(input) {
    const loadingElement = document.getElementById("loading");
    const stealerResultsContainer = document.getElementById("stealerResults");
    const isEmailSearch = isEmail(input);

    loadingElement.classList.remove("hidden");
    stealerResultsContainer.innerHTML = "";

    try {
        const responseData = await fetchStealerData(input);
        loadingElement.classList.add("hidden");

        if (responseData.error) {
            stealerResultsContainer.appendChild(createStealerCard(responseData, isEmailSearch));
            return;
        }

        stealerResultsContainer.appendChild(createStealerCard(responseData, isEmailSearch));
    } catch (error) {
        console.error("Error fetching data:", error);
        loadingElement.classList.add("hidden");
        stealerResultsContainer.innerHTML = '<p class="text-red-500">Error fetching data. Please try again.</p>';
    }
}

document.getElementById("searchButton").addEventListener("click", () => {
    const input = document.getElementById("usernameInput").value.trim();
    if (input) displayResults(input);
});

document.getElementById("usernameInput").addEventListener("keypress", (event) => {
    if (event.key === "Enter") {
        const input = event.target.value.trim();
        if (input) displayResults(input);
    }
});