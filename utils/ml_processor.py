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
        self.scaler = None
        self._load_or_create_model()

    def _load_or_create_model(self):
        """Load existing model or create new one with default scaling"""
        try:
            if os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    saved_data = pickle.load(f)
                    self.model = saved_data['model']
                    self.scaler = saved_data['scaler']
                logging.info("Loaded existing format detection model")
            else:
                self.model = RandomForestClassifier(n_estimators=100)
                self.scaler = StandardScaler()
                default_features = np.array([[1000, 50, 0.3, 0.6, 128, 20, 500]])
                self.scaler.fit(default_features)
                logging.info("Created new format detection model with default scaling")
        except Exception as e:
            logging.error(f"Error loading/creating model: {str(e)}")
            self.model = RandomForestClassifier(n_estimators=100)
            self.scaler = StandardScaler()
            default_features = np.array([[1000, 50, 0.3, 0.6, 128, 20, 500]])
            self.scaler.fit(default_features)

    def identify_bank(self, pdf_path: str) -> Tuple[str, float]:
        """Identify the bank based on PDF content"""
        try:
            # Extract text from first page
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                first_page = pdf_reader.pages[0]
                text = first_page.extract_text().upper()

            # Common bank identifiers
            bank_patterns = {
                'ANZ': ['ANZ', 'AUSTRALIA AND NEW ZEALAND BANKING'],
                'Commonwealth': ['COMMONWEALTH BANK', 'CBA', 'COMMBANK'],
                'Westpac': ['WESTPAC', 'WBC'],
                'NAB': ['NATIONAL AUSTRALIA BANK', 'NAB'],
                'St.George': ['ST.GEORGE', 'ST GEORGE'],
                'ING': ['ING DIRECT', 'ING BANK'],
                'Bendigo': ['BENDIGO BANK', 'BENDIGO AND ADELAIDE'],
                'BOQ': ['BANK OF QUEENSLAND', 'BOQ'],
                'Macquarie': ['MACQUARIE BANK', 'MQG'],
                'HSBC': ['HSBC BANK', 'HSBC']
            }

            # Check for bank identifiers
            max_confidence = 0
            identified_bank = 'Unknown'

            for bank, patterns in bank_patterns.items():
                matches = sum(1 for pattern in patterns if pattern in text)
                confidence = matches / len(patterns) if matches > 0 else 0

                if confidence > max_confidence:
                    max_confidence = confidence
                    identified_bank = bank

            logging.info(f"Identified bank: {identified_bank} with confidence: {max_confidence:.2f}")
            return identified_bank, max_confidence

        except Exception as e:
            logging.error(f"Error identifying bank: {str(e)}")
            return 'Unknown', 0.0

    def predict_format(self, pdf_path: str) -> Dict[str, any]:
        """Predict the format of a PDF with enhanced bank detection"""
        try:
            if not os.path.exists(pdf_path):
                logging.error("PDF file not found")
                return {"format": "unknown", "bank": "Unknown", "confidence": 0.0}

            # First identify the bank
            bank_name, bank_confidence = self.identify_bank(pdf_path)

            # Extract features for format detection
            features = self.extract_features(pdf_path)

            if self.model is None or not hasattr(self.model, 'predict'):
                logging.warning("Model not properly trained, using fallback detection")
                return {
                    "format": "unknown",
                    "bank": bank_name,
                    "confidence": bank_confidence
                }

            features_scaled = self.scaler.transform(features)
            format_prediction = self.model.predict(features_scaled)[0]
            format_confidence = np.max(self.model.predict_proba(features_scaled))

            logging.info(f"Format prediction: {format_prediction} (confidence: {format_confidence:.2f})")

            return {
                "format": format_prediction if format_confidence > 0.6 else "unknown",
                "bank": bank_name,
                "confidence": {
                    "format": format_confidence,
                    "bank": bank_confidence
                }
            }

        except Exception as e:
            logging.error(f"Error predicting format: {str(e)}")
            return {"format": "unknown", "bank": "Unknown", "confidence": 0.0}

    def extract_features(self, pdf_path: str) -> np.ndarray:
        """Extract features from PDF for format detection"""
        try:
            features = []

            # Extract text-based features
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                first_page = pdf_reader.pages[0]
                text = first_page.extract_text()

                # Text-based features
                features.extend([
                    len(text),  # Total text length
                    text.count('\n'),  # Number of lines
                    sum(c.isdigit() for c in text) / max(len(text), 1),  # Ratio of numbers
                    sum(c.isalpha() for c in text) / max(len(text), 1),  # Ratio of letters
                ])

            # Image-based features
            images = convert_from_path(pdf_path, first_page=1, last_page=1)
            if images:
                img = images[0]
                img_array = np.array(img.convert('L'))

                features.extend([
                    img_array.mean(),  # Average brightness
                    img_array.std(),   # Standard deviation of brightness
                    len(pytesseract.image_to_string(img)),  # OCR text length
                ])
            else:
                features.extend([0, 0, 0])  # Default values if image conversion fails

            return np.array(features).reshape(1, -1)

        except Exception as e:
            logging.error(f"Error extracting features: {str(e)}")
            return np.zeros((1, 7))

# Initialize global ML detector with error handling
try:
    format_detector = MLFormatDetector()
except Exception as e:
    logging.error(f"Failed to initialize ML detector: {str(e)}")
    format_detector = None