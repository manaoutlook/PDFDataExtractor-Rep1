from extensions import db
from flask_login import UserMixin
import json
from datetime import datetime

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))

class BankTemplate(db.Model):
    __tablename__ = 'bank_template'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    patterns = db.Column(db.Text, nullable=False)  # JSON string of patterns
    layout = db.Column(db.Text, nullable=False)    # JSON string of layout
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_patterns(self):
        return json.loads(self.patterns)

    def set_patterns(self, patterns_dict):
        self.patterns = json.dumps(patterns_dict)

    def get_layout(self):
        return json.loads(self.layout)

    def set_layout(self, layout_dict):
        self.layout = json.dumps(layout_dict)

class TemplateSimilarity(db.Model):
    __tablename__ = 'template_similarity'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('bank_template.id'), nullable=False)
    similar_template_id = db.Column(db.Integer, db.ForeignKey('bank_template.id'), nullable=False)
    similarity_score = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    template = db.relationship('BankTemplate', foreign_keys=[template_id], backref='similarities')
    similar_template = db.relationship('BankTemplate', foreign_keys=[similar_template_id])