import logging
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import pickle
import os
from typing import List, Dict, Optional, Tuple
import pytesseract
from pdf2image import convert_from_path
import PyPDF2

class MLFormatDetector:
    def __init__(self, model_path: str = "models/format_detector.pkl"):
        self.model_path = model_path
        self.model = None
        self.scaler = StandardScaler()
        self._load_or_create_model()
        
    def _load_or_create_model(self):
        """Load existing model or create new one"""
        try:
            if os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    saved_data = pickle.load(f)
                    self.model = saved_data['model']
                    self.scaler = saved_data['scaler']
                logging.info("Loaded existing format detection model")
            else:
                self.model = RandomForestClassifier(n_estimators=100)
                logging.info("Created new format detection model")
        except Exception as e:
            logging.error(f"Error loading/creating model: {str(e)}")
            self.model = RandomForestClassifier(n_estimators=100)

    def extract_features(self, pdf_path: str) -> np.ndarray:
        """Extract features from PDF for format detection"""
        features = []
        try:
            # Extract text-based features
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                first_page = pdf_reader.pages[0]
                text = first_page.extract_text()
                
                # Text-based features
                features.extend([
                    len(text),  # Total text length
                    text.count('\n'),  # Number of lines
                    sum(c.isdigit() for c in text) / (len(text) + 1),  # Ratio of numbers
                    sum(c.isalpha() for c in text) / (len(text) + 1),  # Ratio of letters
                ])

            # Image-based features
            images = convert_from_path(pdf_path, first_page=1, last_page=1)
            if images:
                img = images[0]
                # Convert to grayscale for analysis
                img_array = np.array(img.convert('L'))
                
                # Image features
                features.extend([
                    img_array.mean(),  # Average brightness
                    img_array.std(),   # Standard deviation of brightness
                    len(pytesseract.image_to_string(img)),  # OCR text length
                ])
            
            return np.array(features).reshape(1, -1)
            
        except Exception as e:
            logging.error(f"Error extracting features: {str(e)}")
            return np.zeros((1, 7))  # Return zero features on error

    def train(self, pdf_paths: List[str], labels: List[str]):
        """Train the format detection model"""
        try:
            features = []
            for pdf_path in pdf_paths:
                features.append(self.extract_features(pdf_path).flatten())
            
            X = np.array(features)
            X_scaled = self.scaler.fit_transform(X)
            
            self.model.fit(X_scaled, labels)
            
            # Save the model
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            with open(self.model_path, 'wb') as f:
                pickle.dump({
                    'model': self.model,
                    'scaler': self.scaler
                }, f)
            
            logging.info("Successfully trained format detection model")
            
        except Exception as e:
            logging.error(f"Error training model: {str(e)}")

    def predict_format(self, pdf_path: str) -> str:
        """Predict the format of a PDF"""
        try:
            features = self.extract_features(pdf_path)
            features_scaled = self.scaler.transform(features)
            prediction = self.model.predict(features_scaled)[0]
            confidence = np.max(self.model.predict_proba(features_scaled))
            
            logging.info(f"Format prediction: {prediction} (confidence: {confidence:.2f})")
            return prediction
            
        except Exception as e:
            logging.error(f"Error predicting format: {str(e)}")
            return "unknown"

# Initialize global ML detector
format_detector = MLFormatDetector()
