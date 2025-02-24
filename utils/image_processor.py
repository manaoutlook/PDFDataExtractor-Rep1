import logging
import os
import tempfile
from typing import List, Dict, Optional
import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
import re
import PyPDF2

def is_image_based_pdf(pdf_path: str) -> bool:
    """
    Determine if a PDF is image-based by comparing text extraction methods.
    Returns True if the PDF is primarily image-based, False if it's text-based.
    """
    try:
        # First try direct text extraction
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            direct_text = ''
            for page in pdf_reader.pages[:2]:  # Check first two pages
                direct_text += page.extract_text()

            # If we get substantial text directly, it's likely text-based
            if len(direct_text.strip()) > 100:
                logging.info("PDF appears to be text-based (direct text extraction successful)")
                return False

        # If direct text extraction failed, try OCR
        images = convert_from_path(pdf_path, first_page=1, last_page=1)
        if not images:
            return False

        # Get text from image using OCR
        image_text = pytesseract.image_to_string(images[0])

        # Compare results
        has_ocr_text = len(image_text.strip()) > 100
        if has_ocr_text and not direct_text.strip():
            logging.info("PDF appears to be image-based (OCR successful, direct extraction failed)")
            return True

        return False

    except Exception as e:
        logging.error(f"Error detecting PDF type: {str(e)}")
        return False

def preprocess_image(image: Image.Image) -> Image.Image:
    """
    Preprocess the image for better OCR results.
    """
    try:
        # Convert to grayscale
        image = image.convert('L')

        # Increase contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)

        # Denoise
        image = image.filter(ImageFilter.MedianFilter())

        return image
    except Exception as e:
        logging.error(f"Error in image preprocessing: {str(e)}")
        return image

def extract_table_structure(image: Image.Image) -> List[Dict]:
    """
    Extract table structure from image using OCR and post-processing.
    """
    try:
        # Preprocess image
        processed_image = preprocess_image(image)

        # Get detailed OCR data including bounding boxes
        ocr_data = pytesseract.image_to_data(processed_image, output_type=pytesseract.Output.DICT)

        # Extract lines with confidence above threshold
        lines = []
        current_line = []
        current_line_number = -1

        for i in range(len(ocr_data['text'])):
            text = ocr_data['text'][i].strip()
            conf = int(ocr_data['conf'][i])
            line_num = ocr_data['line_num'][i]

            if conf > 60 and text:  # Filter low-confidence results
                if line_num != current_line_number:
                    if current_line:
                        lines.append(current_line)
                    current_line = []
                    current_line_number = line_num

                current_line.append({
                    'text': text,
                    'left': ocr_data['left'][i],
                    'width': ocr_data['width'][i]
                })

        if current_line:
            lines.append(current_line)

        # Process extracted lines into structured data
        transactions = []
        for line in lines:
            # Sort words by position
            line.sort(key=lambda x: x['left'])

            # Join words with appropriate spacing
            text_parts = [word['text'] for word in line]
            combined_text = ' '.join(text_parts)

            # Try to identify transaction components
            transaction = parse_transaction_line(combined_text)
            if transaction:
                transactions.append(transaction)
                logging.debug(f"Extracted transaction: {transaction}")

        return transactions

    except Exception as e:
        logging.error(f"Error extracting table structure: {str(e)}")
        return []

def parse_transaction_line(text: str) -> Optional[Dict]:
    """
    Parse a line of text into transaction components.
    """
    try:
        # Common date patterns
        date_pattern = r'\d{1,2}[-/\s]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:uary|ruary|ch|il|y|e|ly|ust|tember|ober|ember)?(?:[-/\s]+\d{2,4})?'
        amount_pattern = r'\$?\s*-?\d+(?:,\d{3})*(?:\.\d{2})?'

        # Try to extract date
        date_match = re.search(date_pattern, text, re.IGNORECASE)
        if not date_match:
            return None

        date = date_match.group(0)

        # Remove date from text
        remaining_text = text[date_match.end():].strip()

        # Find amounts
        amounts = re.findall(amount_pattern, remaining_text)

        # Try to categorize amounts based on position and context
        withdrawal = ''
        deposit = ''
        balance = ''

        if amounts:
            # Last amount is usually balance
            balance = amounts[-1]

            # Check remaining amounts for withdrawals/deposits
            if len(amounts) > 1:
                text_before_amount = remaining_text[:remaining_text.find(amounts[0])]
                if any(word in text_before_amount.lower() for word in ['withdraw', 'debit', 'payment', 'transfer']):
                    withdrawal = amounts[0]
                else:
                    deposit = amounts[0]

        # Extract transaction details
        details = re.sub(f'{date_pattern}|{amount_pattern}', '', remaining_text).strip()
        details = re.sub(r'\s+', ' ', details)  # normalize whitespace

        return {
            'Date': date,
            'Transaction Details': details,
            'Withdrawals ($)': withdrawal,
            'Deposits ($)': deposit,
            'Balance ($)': balance
        }

    except Exception as e:
        logging.error(f"Error parsing transaction line: {str(e)}")
        return None

def process_image_based_pdf(pdf_path: str) -> List[Dict]:
    """
    Process an image-based PDF and extract transaction data.
    """
    try:
        logging.info(f"Processing image-based PDF: {pdf_path}")

        # Convert PDF pages to images
        images = convert_from_path(pdf_path)

        all_transactions = []
        for page_num, image in enumerate(images, 1):
            logging.debug(f"Processing page {page_num}")

            # Extract table structure from image
            transactions = extract_table_structure(image)

            if transactions:
                all_transactions.extend(transactions)
                logging.debug(f"Extracted {len(transactions)} transactions from page {page_num}")
            else:
                logging.warning(f"No transactions found on page {page_num}")

        return all_transactions

    except Exception as e:
        logging.error(f"Error processing image-based PDF: {str(e)}")
        return []