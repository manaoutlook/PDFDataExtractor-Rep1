document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const uploadForm = document.getElementById('uploadForm');
    const previewBtn = document.getElementById('previewBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const fileInfo = document.getElementById('fileInfo');
    const fileName = document.getElementById('fileName');
    const progressBar = document.getElementById('progressBar');
    const alertArea = document.getElementById('alertArea');
    const previewSection = document.getElementById('previewSection');
    const previewTableBody = document.getElementById('previewTableBody');
    const processingPreviewSection = document.getElementById('processingPreviewSection');

    // Maximum file size in bytes (16MB)
    const MAX_FILE_SIZE = 16 * 1024 * 1024;

    function showAlert(message, type = 'danger') {
        alertArea.innerHTML = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
    }

    function updateProgress(percent) {
        progressBar.classList.remove('d-none');
        progressBar.querySelector('.progress-bar').style.width = `${percent}%`;
    }

    function validateFile(file) {
        if (!file.type || file.type !== 'application/pdf') {
            showAlert('Please upload a PDF file.');
            return false;
        }

        if (file.size > MAX_FILE_SIZE) {
            showAlert('File size exceeds 16MB limit.');
            return false;
        }

        return true;
    }

    function handleFile(file) {
        if (!validateFile(file)) {
            return;
        }

        fileInfo.classList.remove('d-none');
        fileName.textContent = file.name;
        previewBtn.disabled = false;
        downloadBtn.disabled = false;
        showAlert('File ready for preview and conversion!', 'success');

        // Start processing preview
        showProcessingPreview(file);
    }

    async function showProcessingPreview(file) {
        processingPreviewSection.innerHTML = '<h3>Processing Steps</h3><div class="preview-steps"></div>';
        const previewSteps = processingPreviewSection.querySelector('.preview-steps');

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/process_preview', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || 'Preview processing failed');
            }

            const data = await response.json();

            // Display processing steps
            previewSteps.innerHTML = '';
            data.preview_images.forEach(image => {
                const stepDiv = document.createElement('div');
                stepDiv.className = 'processing-step mb-4';
                stepDiv.innerHTML = `
                    <h4>${image.step} - Page ${image.page}</h4>
                    <div class="preview-image">
                        <img src="/preview_images/${image.path}" alt="${image.step} preview" class="img-fluid">
                    </div>
                `;
                previewSteps.appendChild(stepDiv);
            });

            processingPreviewSection.classList.remove('d-none');

        } catch (error) {
            showAlert(error.message);
            processingPreviewSection.classList.add('d-none');
        }
    }

    function populatePreviewTable(data) {
        previewTableBody.innerHTML = '';
        data.forEach(transaction => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${transaction.Date}</td>
                <td>${transaction['Transaction Details']}</td>
                <td>${transaction['Withdrawals ($)']}</td>
                <td>${transaction['Deposits ($)']}</td>
                <td>${transaction['Balance ($)']}</td>
            `;
            previewTableBody.appendChild(row);
        });
        previewSection.classList.remove('d-none');
    }

    // Preview functionality
    previewBtn.addEventListener('click', async () => {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        previewBtn.disabled = true;
        progressBar.classList.remove('d-none');
        updateProgress(50);

        try {
            const response = await fetch('/preview', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || 'Preview failed');
            }

            const data = await response.json();
            populatePreviewTable(data.data);
            updateProgress(100);
            showAlert('Data preview loaded successfully!', 'success');
        } catch (error) {
            showAlert(error.message);
            previewSection.classList.add('d-none');
        } finally {
            previewBtn.disabled = false;
            setTimeout(() => {
                progressBar.classList.add('d-none');
                updateProgress(0);
            }, 1000);
        }
    });

    // Drag and drop handlers
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        handleFile(file);
        fileInput.files = e.dataTransfer.files;
    });

    // Click to upload
    dropZone.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFile(fileInput.files[0]);
        }
    });

    // Form submission (download)
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('format', document.querySelector('input[name="format"]:checked').value);

        downloadBtn.disabled = true;
        progressBar.classList.remove('d-none');
        updateProgress(50);

        try {
            const response = await fetch('/download', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || 'Conversion failed');
            }

            updateProgress(100);

            // Handle file download
            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = downloadUrl;
            a.download = fileInput.files[0].name.replace('.pdf', 
                document.querySelector('input[name="format"]:checked').value === 'excel' ? '.xlsx' : '.csv');
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(downloadUrl);

            showAlert('Conversion successful!', 'success');
        } catch (error) {
            showAlert(error.message);
        } finally {
            downloadBtn.disabled = false;
            setTimeout(() => {
                progressBar.classList.add('d-none');
                updateProgress(0);
            }, 1000);
        }
    });
});