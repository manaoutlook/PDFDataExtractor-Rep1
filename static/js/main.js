document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const uploadForm = document.getElementById('uploadForm');
    const previewBtn = document.getElementById('previewBtn');
    const areaSelectBtn = document.getElementById('areaSelectBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const fileInfo = document.getElementById('fileInfo');
    const fileName = document.getElementById('fileName');
    const progressBar = document.getElementById('progressBar');
    const alertArea = document.getElementById('alertArea');
    const previewSection = document.getElementById('previewSection');
    const previewTableBody = document.getElementById('previewTableBody');
    const pdfViewerModal = new bootstrap.Modal(document.getElementById('pdfViewerModal'));
    const pdfViewer = document.getElementById('pdfViewer');
    const selectionOverlay = document.getElementById('selectionOverlay');
    const confirmAreaBtn = document.getElementById('confirmAreaBtn');

    // PDF.js initialization
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

    // Maximum file size in bytes (16MB)
    const MAX_FILE_SIZE = 16 * 1024 * 1024;
    let currentPdfDoc = null;
    let currentPage = null;
    let selectionStart = null;
    let selectionBox = null;
    let selectedAreas = [];

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
        areaSelectBtn.disabled = false;
        downloadBtn.disabled = false;
        showAlert('File ready for processing!', 'success');
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

    // PDF Viewer and Selection functionality
    async function loadPdfIntoViewer(file) {
        try {
            const arrayBuffer = await file.arrayBuffer();
            currentPdfDoc = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
            currentPage = await currentPdfDoc.getPage(1);

            const viewport = currentPage.getViewport({ scale: 1.5 });
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');

            canvas.width = viewport.width;
            canvas.height = viewport.height;
            pdfViewer.style.height = `${viewport.height}px`;

            await currentPage.render({
                canvasContext: context,
                viewport: viewport
            }).promise;

            pdfViewer.innerHTML = '';
            pdfViewer.appendChild(canvas);

            // Clear any existing selections
            selectionOverlay.innerHTML = '';
            selectedAreas = [];
        } catch (error) {
            showAlert('Error loading PDF: ' + error.message);
        }
    }

    function startSelection(e) {
        const rect = pdfViewer.getBoundingClientRect();
        selectionStart = {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top
        };

        selectionBox = document.createElement('div');
        selectionBox.className = 'selection-box';
        selectionOverlay.appendChild(selectionBox);

        document.addEventListener('mousemove', updateSelection);
        document.addEventListener('mouseup', endSelection);
    }

    function updateSelection(e) {
        if (!selectionStart || !selectionBox) return;

        const rect = pdfViewer.getBoundingClientRect();
        const currentX = e.clientX - rect.left;
        const currentY = e.clientY - rect.top;

        const left = Math.min(selectionStart.x, currentX);
        const top = Math.min(selectionStart.y, currentY);
        const width = Math.abs(currentX - selectionStart.x);
        const height = Math.abs(currentY - selectionStart.y);

        selectionBox.style.left = `${left}px`;
        selectionBox.style.top = `${top}px`;
        selectionBox.style.width = `${width}px`;
        selectionBox.style.height = `${height}px`;
    }

    function endSelection() {
        if (selectionBox) {
            const rect = selectionBox.getBoundingClientRect();
            const viewerRect = pdfViewer.getBoundingClientRect();

            selectedAreas.push({
                x: (rect.left - viewerRect.left) / viewerRect.width,
                y: (rect.top - viewerRect.top) / viewerRect.height,
                width: rect.width / viewerRect.width,
                height: rect.height / viewerRect.height
            });
        }

        document.removeEventListener('mousemove', updateSelection);
        document.removeEventListener('mouseup', endSelection);
    }

    // Preview functionality
    previewBtn.addEventListener('click', async () => {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        if (selectedAreas.length > 0) {
            formData.append('areas', JSON.stringify(selectedAreas));
        }

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

    // Area Selection functionality
    areaSelectBtn.addEventListener('click', () => {
        if (fileInput.files.length > 0) {
            loadPdfIntoViewer(fileInput.files[0]);
            pdfViewerModal.show();
        }
    });

    pdfViewer.addEventListener('mousedown', startSelection);

    confirmAreaBtn.addEventListener('click', () => {
        if (selectedAreas.length > 0) {
            showAlert('Areas selected successfully! Click Preview Data to process the selected areas.', 'success');
            pdfViewerModal.hide();
        } else {
            showAlert('Please select at least one area before confirming.');
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

        if (selectedAreas.length > 0) {
            formData.append('areas', JSON.stringify(selectedAreas));
        }

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