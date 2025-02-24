import logging
import os
import tempfile
from typing import List, Dict, Optional, Tuple
import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
import re
import PyPDF2
from datetime import datetime
from .ml_processor import format_detector

def is_image_based_pdf(pdf_path: str) -> bool:
    """
    Enhanced PDF type detection using both traditional and ML-based approaches
    """
    try:
        logging.debug(f"Starting enhanced PDF type detection for: {pdf_path}")

        # ML-based prediction
        predicted_format = format_detector.predict_format(pdf_path)
        if predicted_format != "unknown":
            is_image = predicted_format == "image_based"
            logging.info(f"ML model predicted format: {'image-based' if is_image else 'text-based'}")
            return is_image

        # Fallback to traditional detection
        logging.info("Using traditional detection method as fallback")
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            direct_text = ''
            for page in pdf_reader.pages[:2]:
                direct_text += page.extract_text()

        # Try OCR on first page
        images = convert_from_path(pdf_path, first_page=1, last_page=1)
        if not images:
            return False

        ocr_text = pytesseract.image_to_string(images[0])

        # If OCR gets significantly more text than direct extraction, it's likely image-based
        is_image_based = len(ocr_text.strip()) > len(direct_text.strip()) * 1.5
        logging.info(f"Traditional detection result: {'image-based' if is_image_based else 'text-based'}")

        return is_image_based

    except Exception as e:
        logging.error(f"Error in PDF type detection: {str(e)}")
        return False

def find_table_header(image: Image.Image) -> Dict[str, Tuple[int, int]]:
    """
    Detect table header row and determine column positions with enhanced flexibility
    """
    try:
        logging.debug("Attempting to find table header")

        # Enhance image for header detection with multiple attempts
        heights = [0.2, 0.3, 0.15]  # Try different heights for header search
        for height_ratio in heights:
            # Crop and enhance header section
            header_image = image.crop((0, 0, image.width, int(image.height * height_ratio)))
            enhanced = preprocess_image(header_image)

            # Get OCR data with different configurations
            configs = [
                '--oem 3 --psm 6 -c preserve_interword_spaces=1',
                '--oem 3 --psm 1 -c preserve_interword_spaces=1',
                '--oem 3 --psm 3 -c preserve_interword_spaces=1'
            ]

            for custom_config in configs:
                try:
                    header_data = pytesseract.image_to_data(enhanced, output_type=pytesseract.Output.DICT, config=custom_config)

                    # Find header row
                    header_columns = {}
                    header_texts = []

                    # First pass to identify header positions
                    for i in range(len(header_data['text'])):
                        text = header_data['text'][i].upper().strip()
                        if text:
                            header_texts.append(text)
                            x_start = header_data['left'][i]
                            x_end = x_start + header_data['width'][i]

                            # More flexible header matching
                            if any(word in text for word in ['DATE', 'TIME', 'WHEN']):
                                header_columns['date'] = (0, x_end + 20)
                            elif any(word in text for word in ['TRANS', 'DETAIL', 'DESC', 'PART', 'NARR']):
                                header_columns['details'] = (x_start - 20, x_end + 20)
                            elif any(word in text for word in ['WITH', 'DEBIT', 'DR', 'PAID', 'OUT']):
                                header_columns['withdrawals'] = (x_start - 20, x_end + 20)
                            elif any(word in text for word in ['DEP', 'CRED', 'CR', 'RECV', 'IN']):
                                header_columns['deposits'] = (x_start - 20, x_end + 20)
                            elif any(word in text for word in ['BAL', 'TOTAL', 'AMT']):
                                header_columns['balance'] = (x_start - 20, image.width)

                    # If we found enough columns, use this configuration
                    if len(header_columns) >= 3:
                        logging.debug(f"Found header with config: {custom_config}")
                        logging.debug(f"Header texts: {header_texts}")
                        logging.debug(f"Detected columns: {header_columns}")
                        return header_columns

                except Exception as e:
                    logging.debug(f"Failed attempt with config {custom_config}: {str(e)}")
                    continue

        # If no header found, use intelligent column estimation
        logging.warning("Header detection failed, using intelligent column estimation")
        # Determine if the statement layout is vertical or horizontal based on text positions
        try:
            all_text = pytesseract.image_to_string(image)
            lines = all_text.split('\n')
            # Count numbers in different positions to determine layout
            left_nums = sum(1 for line in lines if line.strip() and line.strip()[0].isdigit())
            right_nums = sum(1 for line in lines if line.strip() and line.strip()[-1].isdigit())

            if left_nums > right_nums:
                # Likely vertical layout
                width = image.width
                return {
                    'date': (0, int(width * 0.15)),
                    'details': (int(width * 0.15), int(width * 0.6)),
                    'withdrawals': (int(width * 0.6), int(width * 0.75)),
                    'deposits': (int(width * 0.75), int(width * 0.9)),
                    'balance': (int(width * 0.9), width)
                }
            else:
                # Likely horizontal layout
                width = image.width
                return {
                    'date': (0, int(width * 0.2)),
                    'details': (int(width * 0.2), int(width * 0.5)),
                    'withdrawals': (int(width * 0.5), int(width * 0.7)),
                    'deposits': (int(width * 0.7), int(width * 0.85)),
                    'balance': (int(width * 0.85), width)
                }

        except Exception as layout_error:
            logging.error(f"Layout detection failed: {str(layout_error)}")
            # Return default column positions
            width = image.width
            return {
                'date': (0, int(width * 0.15)),
                'details': (int(width * 0.15), int(width * 0.6)),
                'withdrawals': (int(width * 0.6), int(width * 0.75)),
                'deposits': (int(width * 0.75), int(width * 0.9)),
                'balance': (int(width * 0.9), width)
            }

    except Exception as e:
        logging.error(f"Error in header detection: {str(e)}")
        # Return default column positions
        width = image.width
        return {
            'date': (0, int(width * 0.15)),
            'details': (int(width * 0.15), int(width * 0.6)),
            'withdrawals': (int(width * 0.6), int(width * 0.75)),
            'deposits': (int(width * 0.75), int(width * 0.9)),
            'balance': (int(width * 0.9), width)
        }

def preprocess_image(image: Image.Image) -> Image.Image:
    """
    Enhanced image preprocessing with multiple techniques to improve OCR accuracy
    """
    try:
        # Convert to grayscale
        image = image.convert('L')

        # Increase contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)

        # Increase sharpness
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(2.0)

        # Remove noise
        image = image.filter(ImageFilter.MedianFilter(size=3))

        # Apply advanced thresholding
        np_image = np.array(image)

        # Try different thresholding techniques
        try:
            # Adaptive thresholding
            block_size = 25
            C = 5
            mean = np_image.mean()
            thresh = mean + C
            binary = np_image > thresh

            # If adaptive thresholding produces poor results, try Otsu's method
            if np.sum(binary) < (binary.size * 0.01):  # Less than 1% white pixels
                # Otsu's thresholding
                mean = np_image.mean()
                std = np_image.std()
                thresh = mean + std
                binary = np_image > thresh

            # Return processed image
            processed = Image.fromarray((binary * 255).astype(np.uint8))

            # Additional denoising if needed
            if np.sum(binary) < (binary.size * 0.05):  # Less than 5% white pixels
                processed = processed.filter(ImageFilter.MinFilter(3))

            return processed

        except Exception as thresh_error:
            logging.warning(f"Advanced thresholding failed: {str(thresh_error)}")
            # Fallback to simple thresholding
            thresh = np_image.mean() + np_image.std()
            binary = np_image > thresh
            return Image.fromarray((binary * 255).astype(np.uint8))

    except Exception as e:
        logging.error(f"Error in image preprocessing: {str(e)}")
        return image  # Return original image if processing fails

def extract_table_data(image: Image.Image) -> List[Dict]:
    """
    Extract transaction data from image using OCR and positional analysis with enhanced error handling
    """
    try:
        logging.debug("Starting table data extraction")

        # Find table structure
        try:
            header_columns = find_table_header(image)
        except Exception as header_error:
            logging.error(f"Error in header detection: {str(header_error)}")
            return []

        # Preprocess image
        try:
            processed_image = preprocess_image(image)
        except Exception as preprocess_error:
            logging.error(f"Image preprocessing failed: {str(preprocess_error)}")
            return []

        # Configure OCR with error handling
        try:
            custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
            ocr_data = pytesseract.image_to_data(processed_image, output_type=pytesseract.Output.DICT, config=custom_config)
        except Exception as ocr_error:
            logging.error(f"OCR processing failed: {str(ocr_error)}")
            return []

        # Group text by lines
        lines = []
        current_line = []
        current_y = -1
        y_threshold = 10

        for i in range(len(ocr_data['text'])):
            text = ocr_data['text'][i].strip()
            conf = int(ocr_data['conf'][i])
            x_pos = ocr_data['left'][i]
            y_pos = ocr_data['top'][i]

            if conf < 40 or not text:  # Lowered confidence threshold
                continue

            # Start new line if y position changes significantly
            if current_y == -1 or abs(y_pos - current_y) > y_threshold:
                if current_line:
                    lines.append(sorted(current_line, key=lambda x: x['x']))
                current_line = []
                current_y = y_pos

            current_line.append({
                'text': text,
                'x': x_pos,
                'y': y_pos,
                'width': ocr_data['width'][i]
            })

        if current_line:
            lines.append(sorted(current_line, key=lambda x: x['x']))

        # Process lines into transactions
        transactions = []
        current_transaction = None

        for line in lines:
            line_data = {
                'date': '',
                'details': [],
                'withdrawals': '',
                'deposits': '',
                'balance': ''
            }

            # Classify each word based on position
            for word in line:
                x_pos = word['x']
                text = word['text']

                for col_name, (start, end) in header_columns.items():
                    if start <= x_pos <= end:
                        if col_name == 'date' and is_date(text):
                            line_data['date'] = text
                            logging.debug(f"Found date: {text}")
                        elif col_name == 'details':
                            line_data['details'].append(text)
                        elif col_name in ['withdrawals', 'deposits', 'balance'] and is_amount(text):
                            line_data[col_name] = clean_amount(text)
                            logging.debug(f"Found {col_name}: {text}")

            # Join details
            line_data['details'] = ' '.join(line_data['details'])

            # Handle transaction continuation
            if line_data['date']:  # New transaction
                if current_transaction:
                    if is_valid_transaction(current_transaction):
                        transactions.append(current_transaction)
                        logging.debug(f"Added transaction: {current_transaction}")
                current_transaction = {
                    'Date': line_data['date'],
                    'Transaction Details': line_data['details'],
                    'Withdrawals ($)': line_data['withdrawals'],
                    'Deposits ($)': line_data['deposits'],
                    'Balance ($)': line_data['balance']
                }
            elif current_transaction and line_data['details']:  # Continuation
                current_transaction['Transaction Details'] += '\n' + line_data['details']
                if line_data['withdrawals'] and not current_transaction['Withdrawals ($)']:
                    current_transaction['Withdrawals ($)'] = line_data['withdrawals']
                if line_data['deposits'] and not current_transaction['Deposits ($)']:
                    current_transaction['Deposits ($)'] = line_data['deposits']
                if line_data['balance'] and not current_transaction['Balance ($)']:
                    current_transaction['Balance ($)'] = line_data['balance']

        # Add last transaction
        if current_transaction and is_valid_transaction(current_transaction):
            transactions.append(current_transaction)

        logging.info(f"Extracted {len(transactions)} valid transactions")
        return transactions

    except Exception as e:
        logging.error(f"Error in table extraction: {str(e)}")
        return []

def is_date(text: str) -> bool:
    """Check if text matches date patterns"""
    date_patterns = [
        r'\d{1,2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)',
        r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}'
    ]
    text = text.strip().upper()
    return any(re.match(pattern, text, re.IGNORECASE) for pattern in date_patterns)

def is_amount(text: str) -> bool:
    """Check if text matches amount patterns"""
    # More flexible amount pattern matching
    amount_patterns = [
        r'^[\$]?\s*-?\d+(?:,\d{3})*(?:\.\d{2})?$',  # Standard format
        r'^[\$]?\s*\(?\d+(?:,\d{3})*(?:\.\d{2})?\)?$',  # Parentheses format
        r'^[\$]?\s*\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:CR|DR)?$'  # With CR/DR suffix
    ]
    text = text.strip()
    return any(re.match(pattern, text) for pattern in amount_patterns)

def clean_amount(amount_str: str) -> str:
    """Clean and format amount strings"""
    try:
        if not amount_str:
            return ''
        # Remove currency symbols and cleanup
        amount_str = str(amount_str).replace('$', '').strip()

        # Handle CR/DR suffix
        is_credit = 'CR' in amount_str.upper()
        amount_str = amount_str.upper().replace('CR', '').replace('DR', '').strip()

        # Remove commas
        amount_str = amount_str.replace(',', '')

        # Handle bracketed negative numbers
        if '(' in amount_str and ')' in amount_str:
            amount_str = '-' + amount_str.replace('(', '').replace(')', '')

        # Convert to float to validate and format
        try:
            amount = float(amount_str)
            if not is_credit and amount > 0:  # DR amounts should be negative
                amount = -amount
            return f"{amount:.2f}"
        except ValueError:
            return ''

    except Exception:
        return ''

def is_valid_transaction(transaction: Dict) -> bool:
    """Validate transaction data"""
    try:
        # Must have date and some content
        if not transaction['Date']:
            return False

        # Must have some details or amounts
        has_content = any([
            transaction['Transaction Details'],
            transaction['Withdrawals ($)'],
            transaction['Deposits ($)'],
            transaction['Balance ($)']
        ])
        if not has_content:
            return False

        # Skip header/footer rows
        skip_words = ['opening', 'closing', 'balance', 'total', 'brought', 'carried']
        details_lower = transaction['Transaction Details'].lower()
        if any(word in details_lower for word in skip_words):
            return False

        return True
    except Exception:
        return False

def process_image_based_pdf(pdf_path: str) -> List[Dict]:
    """
    Process an image-based PDF and extract transaction data with robust error handling.
    """
    try:
        logging.info(f"Processing image-based PDF: {pdf_path}")

        # Convert PDF pages to images with higher DPI for better quality
        images = convert_from_path(pdf_path, dpi=300)
        if not images:
            logging.error("Failed to convert PDF to images")
            return []

        all_transactions = []
        for page_num, image in enumerate(images, 1):
            logging.debug(f"Processing page {page_num}")

            try:
                # Extract transactions from the page
                transactions = extract_table_data(image)

                if transactions:
                    all_transactions.extend(transactions)
                    logging.debug(f"Extracted {len(transactions)} transactions from page {page_num}")
                else:
                    logging.warning(f"No transactions found on page {page_num}")
            except Exception as page_error:
                logging.error(f"Error processing page {page_num}: {str(page_error)}")
                continue  # Continue with next page even if one fails

        if not all_transactions:
            logging.warning("No transactions could be extracted from any page")
            return []

        logging.info(f"Successfully extracted {len(all_transactions)} transactions total")
        return all_transactions

    except Exception as e:
        logging.error(f"Error processing image-based PDF: {str(e)}")
        return []