from datetime import datetime
from app import db

class Template(db.Model):
    """Bank statement template model"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    bank_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # ML-related fields
    feature_data = db.Column(db.JSON)  # Store extracted features for ML matching
    confidence_threshold = db.Column(db.Float, default=0.8)
    
    # Relationships
    fields = db.relationship('TemplateField', backref='template', lazy=True, cascade="all, delete-orphan")
    processed_documents = db.relationship('ProcessedDocument', backref='template', lazy=True)

class TemplateField(db.Model):
    """Template field mapping model"""
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('template.id'), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)
    field_type = db.Column(db.String(50), nullable=False)  # date, amount, text, etc.
    x_start = db.Column(db.Float)  # Relative position (0-1)
    x_end = db.Column(db.Float)
    y_start = db.Column(db.Float)
    y_end = db.Column(db.Float)
    regex_pattern = db.Column(db.String(500))  # Optional regex pattern for validation
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # ML detection related fields
    ml_features = db.Column(db.JSON)  # Store ML features for field detection
    confidence_threshold = db.Column(db.Float, default=0.7)

class ProcessedDocument(db.Model):
    """Processed document history"""
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('template.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), nullable=False)  # success, failed, partial
    error_message = db.Column(db.Text)
    
    # Processing statistics
    processing_time = db.Column(db.Float)  # Time taken in seconds
    confidence_score = db.Column(db.Float)  # Overall confidence score
    num_fields_extracted = db.Column(db.Integer)
    num_fields_failed = db.Column(db.Integer)
    
    # Extracted data
    extracted_data = db.Column(db.JSON)  # Store the extracted data
    validation_results = db.Column(db.JSON)  # Store validation results
