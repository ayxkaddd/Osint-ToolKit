async function checkForUpdates() {
    try {
        const response = await fetch('/api/updates/check');
        const update = await response.json();

        if (update) {
            // Format the date
            const date = new Date(update.date);
            const formattedDate = date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });

            // Update modal content
            document.getElementById('updateAuthorAvatar').src = update.author_avatar;
            document.getElementById('updateAuthorName').textContent = update.committer;
            document.getElementById('updateDate').textContent = formattedDate;

            // Handle message and description
            const [message, description] = update.message.split('\n\n');
            document.getElementById('updateMessage').textContent = message;

            const descContainer = document.getElementById('descriptionContainer');
            const descElement = document.getElementById('updateDescription');
            const toggleBtn = document.getElementById('toggleDescription');

            if (description) {
                descElement.textContent = description;
                descContainer.classList.remove('hidden');

                toggleBtn.addEventListener('click', () => {
                    const icon = toggleBtn.querySelector('i');
                    if (descElement.classList.contains('hidden')) {
                        descElement.classList.remove('hidden');
                        icon.style.transform = 'rotate(180deg)';
                    } else {
                        descElement.classList.add('hidden');
                        icon.style.transform = 'rotate(0deg)';
                    }
                });
            } else {
                descContainer.classList.add('hidden');
            }

            // Update stats
            const stats = update.stats;
            document.getElementById('updateTotalChanges').textContent = `${stats.total} changes`;
            document.getElementById('updateAdditions').textContent = `+${stats.additions}`;
            document.getElementById('updateDeletions').textContent = `-${stats.deletions}`;

            // Calculate percentages for the bars
            const maxChanges = Math.max(stats.additions, stats.deletions);
            const additionsWidth = (stats.additions / maxChanges) * 100;
            const deletionsWidth = (stats.deletions / maxChanges) * 100;

            // Animate the bars
            setTimeout(() => {
                document.getElementById('updateAdditionsBar').style.width = `${additionsWidth}%`;
                document.getElementById('updateDeletionsBar').style.width = `${deletionsWidth}%`;
            }, 100);

            openUpdateModal();
        } else {
            showTemporaryNotification('You are up to date!', 'success');
        }
    } catch (error) {
        console.error('Error checking for updates:', error);
        showTemporaryNotification('Failed to check for updates', 'error');
    }
}

function openUpdateModal() {
    const modal = document.getElementById('updateModal');
    const modalContent = modal.querySelector('div');

    modal.classList.remove('hidden');
    modal.classList.add('flex');

    setTimeout(() => {
        modal.classList.remove('opacity-0');
        modalContent.classList.remove('scale-95', 'opacity-0');
    }, 10);
}

function closeUpdateModal() {
    const modal = document.getElementById('updateModal');
    const modalContent = modal.querySelector('div');

    modal.classList.add('opacity-0');
    modalContent.classList.add('scale-95', 'opacity-0');

    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }, 300);
}

function showTemporaryNotification(message, type = 'success') {
    const notification = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-green-500' : 'bg-red-500';
    notification.className = `fixed bottom-4 right-4 ${bgColor} text-white px-6 py-3 rounded-lg shadow-lg transform transition-all duration-300 translate-y-full opacity-0`;
    notification.innerHTML = `
        <div class="flex items-center space-x-2">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
            <span>${message}</span>
        </div>
    `;
    document.body.appendChild(notification);

    setTimeout(() => {
        notification.classList.remove('translate-y-full', 'opacity-0');
    }, 100);

    setTimeout(() => {
        notification.classList.add('translate-y-full', 'opacity-0');
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 3000);
}