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

def identify_table_columns(ocr_data) -> Dict[str, range]:
    """
    Identify column positions based on headers and content alignment.
    """
    try:
        # Expected column headers and their variations
        header_patterns = {
            'date': r'(?:Date|DATE)',
            'details': r'(?:Transaction Details|TRANSACTION DETAILS|Description|DESCRIPTION)',
            'withdrawals': r'(?:Withdrawals|WITHDRAWALS|Debit|DEBIT)\s*\(?(?:\$|AUD)?\)?',
            'deposits': r'(?:Deposits|DEPOSITS|Credit|CREDIT)\s*\(?(?:\$|AUD)?\)?',
            'balance': r'(?:Balance|BALANCE)\s*\(?(?:\$|AUD)?\)?'
        }

        # Find header positions
        column_ranges = {}
        header_positions = []

        # Combine all text in the first few lines to find headers
        first_lines = []
        current_line = -1
        for i in range(len(ocr_data['text'])):
            if ocr_data['line_num'][i] != current_line:
                if len(first_lines) >= 3:  # Only check first 3 lines
                    break
                current_line = ocr_data['line_num'][i]
                first_lines.append([])
            first_lines[-1].append({
                'text': ocr_data['text'][i],
                'left': ocr_data['left'][i],
                'width': ocr_data['width'][i]
            })

        # Search for headers in the first few lines
        for line in first_lines:
            line_text = ' '.join(word['text'] for word in line)
            for col_name, pattern in header_patterns.items():
                match = re.search(pattern, line_text, re.IGNORECASE)
                if match:
                    # Find the word containing the header
                    for word in line:
                        if re.search(pattern, word['text'], re.IGNORECASE):
                            header_positions.append({
                                'name': col_name,
                                'left': word['left'],
                                'right': word['left'] + word['width']
                            })

        # Sort headers by position
        header_positions.sort(key=lambda x: x['left'])

        # Create column ranges
        for i, header in enumerate(header_positions):
            if i < len(header_positions) - 1:
                column_ranges[header['name']] = range(
                    header['left'],
                    header_positions[i + 1]['left']
                )
            else:
                column_ranges[header['name']] = range(
                    header['left'],
                    header['left'] + 500  # Assume last column extends
                )

        return column_ranges

    except Exception as e:
        logging.error(f"Error identifying table columns: {str(e)}")
        return {}

def extract_table_structure(image: Image.Image) -> List[Dict]:
    """
    Extract table structure from image using OCR and post-processing.
    """
    try:
        # Preprocess image
        processed_image = preprocess_image(image)

        # Get detailed OCR data including bounding boxes
        ocr_data = pytesseract.image_to_data(processed_image, output_type=pytesseract.Output.DICT)

        # Identify column positions
        column_ranges = identify_table_columns(ocr_data)
        if not column_ranges:
            logging.error("Failed to identify table columns")
            return []

        # Extract lines with confidence above threshold
        lines = []
        current_line = {
            'date': [],
            'details': [],
            'withdrawals': [],
            'deposits': [],
            'balance': []
        }
        current_line_number = -1

        for i in range(len(ocr_data['text'])):
            text = ocr_data['text'][i].strip()
            conf = int(ocr_data['conf'][i])
            line_num = ocr_data['line_num'][i]
            left_pos = ocr_data['left'][i]

            if conf > 60 and text:  # Filter low-confidence results
                # Determine which column this text belongs to
                for col_name, col_range in column_ranges.items():
                    if left_pos in col_range:
                        if line_num != current_line_number:
                            if any(col for col in current_line.values()):
                                lines.append(current_line)
                            current_line = {
                                'date': [],
                                'details': [],
                                'withdrawals': [],
                                'deposits': [],
                                'balance': []
                            }
                            current_line_number = line_num
                        current_line[col_name].append(text)
                        break

        # Add last line if not empty
        if any(col for col in current_line.values()):
            lines.append(current_line)

        # Process lines into transactions
        transactions = []
        for line in lines:
            # Join column texts
            date = ' '.join(line['date'])
            details = ' '.join(line['details'])
            withdrawals = ' '.join(line['withdrawals'])
            deposits = ' '.join(line['deposits'])
            balance = ' '.join(line['balance'])

            # Clean and format the data
            clean_date = parse_date(date)
            if clean_date:
                transaction = {
                    'Date': clean_date,
                    'Transaction Details': details.strip(),
                    'Withdrawals ($)': clean_amount(withdrawals),
                    'Deposits ($)': clean_amount(deposits),
                    'Balance ($)': clean_amount(balance)
                }
                if is_valid_transaction(transaction):
                    transactions.append(transaction)
                    logging.debug(f"Extracted transaction: {transaction}")

        return transactions

    except Exception as e:
        logging.error(f"Error extracting table structure: {str(e)}")
        return []

def clean_amount(amount_str: str) -> str:
    """Clean and format amount strings"""
    try:
        if not amount_str:
            return ''
        # Remove currency symbols and cleanup
        amount_str = re.sub(r'[^\d.-]', '', amount_str)
        # Handle negative amounts
        if amount_str.startswith('-'):
            amount_str = amount_str[1:]
            return f"-{amount_str}"
        return amount_str
    except Exception:
        return ''

def parse_date(date_str: str) -> str:
    """Parse date string from bank statement format"""
    try:
        if not date_str:
            return ''

        # Remove any unwanted text
        date_str = re.sub(r'(?i)(opening|balance|closing|total|date)', '', date_str).strip()

        # Match date patterns
        patterns = [
            r'(\d{1,2})[-/\s]+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)',
            r'(\d{1,2})[-/\s]+(January|February|March|April|May|June|July|August|September|October|November|December)',
        ]

        for pattern in patterns:
            match = re.search(pattern, date_str, re.IGNORECASE)
            if match:
                day = match.group(1)
                month = match.group(2)[:3].title()
                return f"{int(day):02d} {month}"

        return ''
    except Exception:
        return ''

def is_valid_transaction(transaction: Dict) -> bool:
    """
    Validate transaction data to ensure it's a real transaction
    """
    try:
        # Must have a valid date
        if not transaction['Date']:
            return False

        # Must have some transaction details
        if not transaction['Transaction Details']:
            return False

        # Must have at least one amount (withdrawal, deposit, or balance)
        has_amount = any([
            transaction['Withdrawals ($)'],
            transaction['Deposits ($)'],
            transaction['Balance ($)']
        ])
        if not has_amount:
            return False

        # Skip header or footer rows
        skip_keywords = ['opening', 'closing', 'balance', 'total', 'brought', 'carried']
        if any(keyword in transaction['Transaction Details'].lower() for keyword in skip_keywords):
            return False

        return True

    except Exception:
        return False

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