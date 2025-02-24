import os
import logging
from flask import Flask
from extensions import db

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

if __name__ == '__main__':
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

    app.run(host='0.0.0.0', port=5000, debug=True)