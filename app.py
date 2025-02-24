import os
import logging
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from utils.converter import convert_pdf, convert_pdf_to_data
from utils.image_processor import preprocess_image, process_image_based_pdf, is_image_based_pdf
import tempfile
import uuid
from pdf2image import convert_from_path
from PIL import Image

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Configuration
ALLOWED_EXTENSIONS = {'pdf'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
PREVIEW_FOLDER = 'static/preview_images'

# Ensure preview folder exists
os.makedirs(PREVIEW_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/preview', methods=['POST'])
def preview_data():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    force_text_based = request.form.get('force_text_based', 'false').lower() == 'true'

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400

    try:
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, secure_filename(file.filename))
            file.save(pdf_path)

            logging.debug(f"Starting preview of {pdf_path}")
            data = convert_pdf_to_data(pdf_path, force_text_based=force_text_based)

            if not data:
                return jsonify({'error': 'No transactions could be extracted from the PDF'}), 500

            return jsonify({'data': data})

    except Exception as e:
        logging.error(f"Error during preview: {str(e)}")
        return jsonify({'error': 'An error occurred during preview'}), 500

@app.route('/process_preview', methods=['POST'])
def process_preview():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400

    try:
        # Create unique ID for this processing session
        session_id = str(uuid.uuid4())
        session_folder = os.path.join(PREVIEW_FOLDER, session_id)
        os.makedirs(session_folder, exist_ok=True)

        # Save and process the PDF
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, secure_filename(file.filename))
            file.save(pdf_path)

            # Check if PDF is image-based
            is_image_pdf = is_image_based_pdf(pdf_path)

            # Convert PDF to images
            images = convert_from_path(pdf_path, dpi=300)
            if not images:
                return jsonify({'error': 'Failed to convert PDF to images'}), 500

            preview_images = []
            for idx, image in enumerate(images):
                # Save original image
                original_path = f"original_page_{idx+1}.png"
                image.save(os.path.join(session_folder, original_path))
                preview_images.append({
                    'step': 'Original',
                    'page': idx + 1,
                    'path': f"{session_id}/{original_path}"
                })

                # Process image and save intermediate steps
                processed = preprocess_image(image)
                processed_path = f"processed_page_{idx+1}.png"
                processed.save(os.path.join(session_folder, processed_path))
                preview_images.append({
                    'step': 'Processed',
                    'page': idx + 1,
                    'path': f"{session_id}/{processed_path}"
                })

            return jsonify({
                'success': True,
                'is_image_based': is_image_pdf,
                'preview_images': preview_images,
                'session_id': session_id
            })

    except Exception as e:
        logging.error(f"Error during processing preview: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/preview_images/<path:filename>')
def preview_images(filename):
    return send_from_directory(PREVIEW_FOLDER, filename)

@app.route('/download', methods=['POST'])
def download_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    output_format = request.form.get('format', 'excel')

    try:
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, secure_filename(file.filename))
            file.save(pdf_path)

            logging.debug(f"Starting conversion of {pdf_path} to {output_format}")
            output_file = convert_pdf(pdf_path, output_format)

            if not output_file:
                return jsonify({'error': 'No transactions could be extracted from the PDF'}), 500

            if not os.path.exists(output_file):
                logging.error(f"Output file not found at {output_file}")
                return jsonify({'error': 'Output file generation failed'}), 500

            extension = 'xlsx' if output_format == 'excel' else 'csv'
            return send_file(
                output_file,
                as_attachment=True,
                download_name=f'converted.{extension}'
            )

    except Exception as e:
        logging.error(f"Error during conversion: {str(e)}")
        return jsonify({'error': 'An error occurred during conversion'}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)