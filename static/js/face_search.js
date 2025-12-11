document.addEventListener('DOMContentLoaded', () => {
    // Initialize Lucide icons
    lucide.createIcons();

    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const previewSection = document.getElementById('previewSection');
    const previewImage = document.getElementById('previewImage');
    const overlayCanvas = document.getElementById('overlayCanvas');
    const detectButton = document.getElementById('detectButton');
    const searchButton = document.getElementById('searchButton');
    const resetButton = document.getElementById('resetButton');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const loadingText = document.getElementById('loadingText');
    const resultsSection = document.getElementById('resultsSection');
    const resultsGrid = document.getElementById('resultsGrid');

    let currentFile = null;
    let detectedFaces = [];
    let selectedFaceIndex = null;

    // Upload Area Event Listeners
    uploadArea.addEventListener('click', () => fileInput.click());

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('drag-over');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('drag-over');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) {
            handleFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFile(e.target.files[0]);
        }
    });

    function handleFile(file) {
        if (!file.type.startsWith('image/')) {
            showTemporaryNotification('Please upload an image file.');
            return;
        }

        currentFile = file;
        const reader = new FileReader();
        reader.onload = (e) => {
            previewImage.src = e.target.result;
            uploadArea.classList.add('hidden');
            previewSection.classList.remove('hidden');
            // Reset state
            detectedFaces = [];
            selectedFaceIndex = null;
            searchButton.classList.add('hidden');
            resultsSection.classList.add('hidden');
            resultsGrid.innerHTML = '';
            clearCanvas();
        };
        reader.readAsDataURL(file);
    }

    // Detect Faces
    detectButton.addEventListener('click', async () => {
        if (!currentFile) return;

        setLoading(true, 'Detecting faces...');

        const formData = new FormData();
        formData.append('image', currentFile);

        try {
            const response = await fetch('/api/face-search/detect-faces', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) throw new Error('Failed to detect faces');

            const data = await response.json();
            detectedFaces = data.faces;

            if (detectedFaces.length === 0) {
                showTemporaryNotification('No faces detected.', 'error');
            } else if (detectedFaces.length === 1) {
                // Only one face, auto-select it
                selectedFaceIndex = 0;
                drawFaces(detectedFaces, selectedFaceIndex);
                searchButton.classList.remove('hidden');
            } else {
                // Multiple faces, allow selection
                drawFaces(detectedFaces, null);
                searchButton.classList.remove('hidden');
            }
        } catch (error) {
            console.error('Error:', error);
            showTemporaryNotification('Error detecting faces: ' + error.message, 'error');
        } finally {
            setLoading(false);
        }
    });

    // Canvas click handler for face selection
    overlayCanvas.addEventListener('click', (e) => {
        if (detectedFaces.length <= 1) return;

        const rect = overlayCanvas.getBoundingClientRect();
        const scaleX = overlayCanvas.width / rect.width;
        const scaleY = overlayCanvas.height / rect.height;
        const clickX = (e.clientX - rect.left) * scaleX;
        const clickY = (e.clientY - rect.top) * scaleY;

        // Check which face was clicked
        for (let i = 0; i < detectedFaces.length; i++) {
            const face = detectedFaces[i];
            if (clickX >= face.x1 && clickX <= face.x2 &&
                clickY >= face.y1 && clickY <= face.y2) {
                selectedFaceIndex = i;
                drawFaces(detectedFaces, selectedFaceIndex);
                break;
            }
        }
    });

    // Search Faces
    searchButton.addEventListener('click', async () => {
        if (!currentFile) return;

        if (detectedFaces.length > 1 && selectedFaceIndex === null) {
            showTemporaryNotification('Please select a face to search by clicking on it.', 'error');
            return;
        }

        setLoading(true, 'Searching for matches...');
        resultsSection.classList.add('hidden');
        resultsGrid.innerHTML = '';

        try {
            let imageToSearch;

            if (detectedFaces.length === 1 || selectedFaceIndex !== null) {
                // Crop the selected face
                const faceIndex = selectedFaceIndex !== null ? selectedFaceIndex : 0;
                imageToSearch = await cropFace(previewImage, detectedFaces[faceIndex]);
            } else {
                imageToSearch = currentFile;
            }

            const formData = new FormData();
            formData.append('image', imageToSearch);

            const response = await fetch('/api/face-search/search', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) throw new Error('Failed to search faces');

            const results = await response.json();
            displayResults(results);
        } catch (error) {
            console.error('Error:', error);
            showTemporaryNotification('Error searching faces: ' + error.message, 'error');
        } finally {
            setLoading(false);
        }
    });

    // Reset
    resetButton.addEventListener('click', () => {
        currentFile = null;
        detectedFaces = [];
        selectedFaceIndex = null;
        fileInput.value = '';
        previewImage.src = '';
        uploadArea.classList.remove('hidden');
        previewSection.classList.add('hidden');
        resultsSection.classList.add('hidden');
        resultsGrid.innerHTML = '';
        clearCanvas();
    });

    function setLoading(isLoading, text) {
        if (isLoading) {
            loadingIndicator.classList.remove('hidden');
            loadingText.textContent = text;
            detectButton.disabled = true;
            searchButton.disabled = true;
        } else {
            loadingIndicator.classList.add('hidden');
            detectButton.disabled = false;
            searchButton.disabled = false;
        }
    }

    function clearCanvas() {
        const ctx = overlayCanvas.getContext('2d');
        ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    }

    function drawFaces(faces, selectedIndex) {
        // Adjust canvas size to match image
        overlayCanvas.width = previewImage.naturalWidth;
        overlayCanvas.height = previewImage.naturalHeight;

        // Scale canvas to display size
        const displayWidth = previewImage.width;
        const displayHeight = previewImage.height;
        overlayCanvas.style.width = `${displayWidth}px`;
        overlayCanvas.style.height = `${displayHeight}px`;

        const ctx = overlayCanvas.getContext('2d');
        ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

        faces.forEach((face, index) => {
            const width = face.x2 - face.x1;
            const height = face.y2 - face.y1;

            // Draw rectangle
            if (selectedIndex !== null && index === selectedIndex) {
                // Selected face - bright purple with thicker border
                ctx.strokeStyle = '#a855f7';
                ctx.lineWidth = 6;
                ctx.fillStyle = 'rgba(168, 85, 247, 0.2)';
                ctx.fillRect(face.x1, face.y1, width, height);
            } else {
                // Unselected face - dim purple
                ctx.strokeStyle = selectedIndex === null ? '#a855f7' : '#6b7280';
                ctx.lineWidth = 4;
            }
            
            ctx.strokeRect(face.x1, face.y1, width, height);

            // Draw face number if multiple faces
            if (faces.length > 1) {
                ctx.fillStyle = selectedIndex !== null && index === selectedIndex ? '#a855f7' : '#6b7280';
                ctx.font = 'bold 24px sans-serif';
                ctx.fillText(`${index + 1}`, face.x1 + 10, face.y1 + 35);
            }
        });

        // Make canvas clickable if multiple faces
        if (faces.length > 1) {
            overlayCanvas.style.cursor = 'pointer';
        } else {
            overlayCanvas.style.cursor = 'default';
        }
    }

    async function cropFace(imgElement, face) {
        return new Promise((resolve) => {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');

            // Add padding around face (20% on each side)
            const padding = 0.2;
            const width = face.x2 - face.x1;
            const height = face.y2 - face.y1;
            const paddedWidth = width * (1 + padding * 2);
            const paddedHeight = height * (1 + padding * 2);
            const x = Math.max(0, face.x1 - width * padding);
            const y = Math.max(0, face.y1 - height * padding);

            canvas.width = paddedWidth;
            canvas.height = paddedHeight;

            ctx.drawImage(
                imgElement,
                x, y, paddedWidth, paddedHeight,
                0, 0, paddedWidth, paddedHeight
            );

            canvas.toBlob((blob) => {
                resolve(new File([blob], 'cropped_face.jpg', { type: 'image/jpeg' }));
            }, 'image/jpeg', 0.95);
        });
    }

    function displayResults(results) {
        resultsSection.classList.remove('hidden');

        if (results.length === 0) {
            resultsGrid.innerHTML = '<p class="text-gray-400 col-span-full text-center">No matches found.</p>';
            return;
        }

        results.forEach(result => {
            const similarity = parseFloat(result.similarity_rate);
            let similarityClass = 'similarity-low';
            if (similarity > 0.7) similarityClass = 'similarity-high';
            else if (similarity > 0.5) similarityClass = 'similarity-medium';

            const card = document.createElement('div');
            card.className = 'result-card relative group';

            card.innerHTML = `
                <div class="relative aspect-square overflow-hidden">
                    <img src="${result.image_url}" alt="${result.name}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300">
                    <div class="similarity-badge ${similarityClass}">
                        ${similarity}% Match
                    </div>
                </div>
                <div class="p-4">
                    <h3 class="font-bold text-lg text-white mb-1 truncate">${result.name}</h3>
                    <div class="space-y-2 text-sm text-gray-400">
                        <div class="flex items-center">
                            <i data-lucide="map-pin" class="w-4 h-4 mr-2"></i>
                            <span class="truncate">${result.city || 'Unknown City'}</span>
                        </div>
                        <div class="flex items-center">
                            <i data-lucide="external-link" class="w-4 h-4 mr-2"></i>
                            <a href="https://vk.com/id${result.vk_id}" target="_blank" class="text-blue-400 hover:text-blue-300 hover:underline truncate">
                                VK Profile
                            </a>
                        </div>
                    </div>
                </div>
            `;

            resultsGrid.appendChild(card);
        });

        lucide.createIcons();
    }
});