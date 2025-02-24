import os
import logging
import tempfile
from flask import render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from app import app
from utils.converter import convert_pdf, convert_pdf_to_data
import tabula
import PyPDF2

# Configure logging
logger = logging.getLogger(__name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf'}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/test_pdf', methods=['POST'])
def test_pdf():
    """Test endpoint to analyze PDF structure"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, secure_filename(file.filename))
            file.save(pdf_path)

            # Extract text content
            with open(pdf_path, 'rb') as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                text_content = []
                for page in pdf_reader.pages:
                    text_content.append(page.extract_text())

            # Extract tables using tabula
            tables = tabula.read_pdf(
                pdf_path,
                pages='all',
                multiple_tables=True,
                guess=False,
                lattice=False,
                stream=True,
                columns=[70, 250, 350, 450, 550],
                area=[150, 50, 750, 550],
                relative_area=False,
                pandas_options={'header': None}
            )

            # Convert tables to list format for JSON serialization
            table_data = []
            for i, table in enumerate(tables):
                table_data.append({
                    'page': i + 1,
                    'shape': table.shape,
                    'columns': list(table.columns),
                    'rows': table.values.tolist()
                })

            return jsonify({
                'filename': file.filename,
                'num_pages': len(pdf_reader.pages),
                'text_content': text_content,
                'tables_found': len(tables),
                'table_data': table_data
            })

    except Exception as e:
        logger.error(f"Error in PDF analysis: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/preview', methods=['POST'])
def preview_data():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400

    try:
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, secure_filename(file.filename))
            file.save(pdf_path)

            logger.debug(f"Starting preview of {pdf_path}")
            data = convert_pdf_to_data(pdf_path)

            if not data:
                return jsonify({'error': 'No transactions could be extracted from the PDF'}), 500

            return jsonify({'data': data})

    except Exception as e:
        logger.error(f"Error during preview: {str(e)}")
        return jsonify({'error': 'An error occurred during preview'}), 500

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

            logger.debug(f"Starting conversion of {pdf_path} to {output_format}")
            output_file = convert_pdf(pdf_path, output_format)

            if not output_file:
                return jsonify({'error': 'No transactions could be extracted from the PDF'}), 500

            if not os.path.exists(output_file):
                logger.error(f"Output file not found at {output_file}")
                return jsonify({'error': 'Output file generation failed'}), 500

            extension = 'xlsx' if output_format == 'excel' else 'csv'
            return send_file(
                output_file,
                as_attachment=True,
                download_name=f'converted.{extension}'
            )

    except Exception as e:
        logger.error(f"Error during conversion: {str(e)}")
        return jsonify({'error': 'An error occurred during conversion'}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413