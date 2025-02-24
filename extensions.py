from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import declarative_base

# Create the base class for SQLAlchemy models
Base = declarative_base()

# Initialize SQLAlchemy with the base class
db = SQLAlchemy(model_class=Base)
