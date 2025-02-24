import os
import logging
from flask import Flask
from extensions import db
import tempfile
from werkzeug.utils import secure_filename
from flask import render_template, request, jsonify, send_file

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Configure database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize the database with the app
db.init_app(app)

# Configuration
ALLOWED_EXTENSIONS = {'pdf'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

with app.app_context():
    try:
        # Import models and create tables
        import models  # noqa: F401
        logger.info("Starting database initialization...")
        db.create_all()
        logger.info("Database tables created successfully")

        # Log table creation status
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        for table_name in inspector.get_table_names():
            logger.info(f"Created table: {table_name}")
            columns = [col['name'] for col in inspector.get_columns(table_name)]
            logger.info(f"Table {table_name} columns: {', '.join(columns)}")

        # Import views after db initialization
        from views import *  # noqa: F403
        logger.info("Views imported successfully")

    except Exception as e:
        logger.error(f"Error during database initialization: {str(e)}")
        raise

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

from utils.converter import convert_pdf, convert_pdf_to_data

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)