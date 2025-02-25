import os
import logging
from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.utils import secure_filename
from utils.converter import convert_pdf, convert_pdf_to_data
import tempfile

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Database Configuration
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
db.init_app(app)

# Configuration
ALLOWED_EXTENSIONS = {'pdf'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

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

            result = convert_pdf_to_data(pdf_path)

            if not result or not result.get('data'):
                return jsonify({
                    'error': 'Unable to extract data from the PDF. Please ensure it contains transaction data in a table format.',
                    'details': 'The system could not identify any transaction data in the uploaded file.'
                }), 422

            return jsonify(result)

    except Exception as e:
        logging.error(f"Error during preview: {str(e)}")
        return jsonify({
            'error': 'An error occurred while processing the file',
            'details': str(e) if app.debug else 'Please try again or contact support if the issue persists.'
        }), 500

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
                return jsonify({
                    'error': 'Unable to convert the PDF',
                    'details': 'No transaction data could be extracted from the file.'
                }), 422

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
        return jsonify({
            'error': 'An error occurred during conversion',
            'details': str(e) if app.debug else 'Please try again or contact support if the issue persists.'
        }), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413

# Initialize database tables
with app.app_context():
    try:
        logging.info("Initializing database...")
        import models  # noqa: F401
        db.create_all()
        logging.info("Database initialized successfully")
    except Exception as e:
        logging.error(f"Error initializing database: {str(e)}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)