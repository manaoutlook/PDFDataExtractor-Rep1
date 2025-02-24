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
import tabula

logging.basicConfig(level=logging.DEBUG)

def analyze_page_content(page_reader, page_image) -> str:
    """
    Analyze a single page to determine if it's text-based, image-based, or mixed.
    Returns: 'text', 'image', or 'mixed'
    """
    try:
        # Extract text directly from PDF
        direct_text = page_reader.extract_text()
        direct_text_len = len(direct_text.strip())
        logging.debug(f"Direct text extraction length: {direct_text_len}")

        # Try OCR on the page image
        ocr_text = pytesseract.image_to_string(page_image)
        ocr_text_len = len(ocr_text.strip())
        logging.debug(f"OCR text extraction length: {ocr_text_len}")

        # Determine page type based on text lengths
        if direct_text_len > 100 and ocr_text_len > 100:
            # If both methods get substantial text, it's likely mixed
            if abs(direct_text_len - ocr_text_len) > 100:
                logging.info("Page appears to be mixed content")
                return 'mixed'
            else:
                logging.info("Page appears to be text-based")
                return 'text'
        elif direct_text_len > 100:
            logging.info("Page appears to be text-based")
            return 'text'
        elif ocr_text_len > 100:
            logging.info("Page appears to be image-based")
            return 'image'
        else:
            logging.warning("Page content type unclear, defaulting to image-based")
            return 'image'

    except Exception as e:
        logging.error(f"Error analyzing page content: {str(e)}")
        return 'image'  # Default to image-based processing if analysis fails

def is_image_based_pdf(pdf_path: str) -> Tuple[bool, List[str]]:
    """
    Analyze PDF to determine if it's image-based and return page types.
    Returns: (is_primarily_image_based, list_of_page_types)
    """
    try:
        logging.debug(f"Analyzing PDF content types: {pdf_path}")

        # Open PDF for direct text extraction
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            # Convert PDF to images
            images = convert_from_path(pdf_path)

            page_types = []
            image_pages = 0

            # Analyze each page
            for page_num, image in enumerate(images):
                page_reader = pdf_reader.pages[page_num]
                page_type = analyze_page_content(page_reader, image)
                page_types.append(page_type)
                if page_type in ['image', 'mixed']:
                    image_pages += 1

            # Determine if PDF is primarily image-based
            is_primarily_image = image_pages >= len(images) / 2
            logging.info(f"PDF analysis - Total pages: {len(images)}, Image/Mixed pages: {image_pages}")
            logging.info(f"Page types: {page_types}")

            return is_primarily_image, page_types

    except Exception as e:
        logging.error(f"Error analyzing PDF: {str(e)}")
        return True, ['image']  # Default to image-based if analysis fails

def find_table_header(image: Image.Image) -> Dict[str, Tuple[int, int]]:
    """
    Detect table header row and determine column positions
    """
    try:
        logging.debug("Attempting to find table header")

        # Enhance image for header detection
        header_image = image.crop((0, 0, image.width, int(image.height * 0.2)))
        enhanced = preprocess_image(header_image)

        # Get OCR data for header
        custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
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

                if 'DATE' in text:
                    header_columns['date'] = (0, x_end + 20)
                elif any(word in text for word in ['TRANSACTION', 'DETAILS', 'DESCRIPTION']):
                    header_columns['details'] = (x_start - 20, x_end + 20)
                elif any(word in text for word in ['WITHDRAWAL', 'DEBIT', 'DR']):
                    header_columns['withdrawals'] = (x_start - 20, x_end + 20)
                elif any(word in text for word in ['DEPOSIT', 'CREDIT', 'CR']):
                    header_columns['deposits'] = (x_start - 20, x_end + 20)
                elif 'BALANCE' in text:
                    header_columns['balance'] = (x_start - 20, image.width)

        logging.debug(f"Found header texts: {header_texts}")
        logging.debug(f"Detected header columns: {header_columns}")

        # If balance column not found, use last section of the image
        if 'balance' not in header_columns and header_columns:
            last_col_end = max(col[1] for col in header_columns.values())
            header_columns['balance'] = (last_col_end, image.width)
            logging.debug("Added balance column based on last position")

        if not header_columns:
            logging.warning("Header detection failed, using default column positions")
            # Fallback to fixed positions
            width = image.width
            header_columns = {
                'date': (0, int(width * 0.15)),
                'details': (int(width * 0.15), int(width * 0.6)),
                'withdrawals': (int(width * 0.6), int(width * 0.75)),
                'deposits': (int(width * 0.75), int(width * 0.9)),
                'balance': (int(width * 0.9), width)
            }

        return header_columns

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
    Apply multiple preprocessing steps to improve OCR accuracy
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

        # Apply adaptive thresholding
        np_image = np.array(image)
        block_size = 25
        C = 5
        mean = np_image.mean()
        thresh = mean + C
        binary = np_image > thresh

        # Return processed image
        processed = Image.fromarray((binary * 255).astype(np.uint8))
        return processed

    except Exception as e:
        logging.error(f"Error in image preprocessing: {str(e)}")
        return image

def extract_table_data(image: Image.Image) -> List[Dict]:
    """
    Extract transaction data from image using OCR and positional analysis
    """
    try:
        logging.debug("Starting table data extraction")

        # Find table structure
        header_columns = find_table_header(image)

        # Preprocess image
        processed_image = preprocess_image(image)

        # Configure OCR
        custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
        ocr_data = pytesseract.image_to_data(processed_image, output_type=pytesseract.Output.DICT, config=custom_config)

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
    Process an image-based PDF and extract transaction data.
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

            # Extract transactions from the page
            transactions = extract_table_data(image)

            if transactions:
                all_transactions.extend(transactions)
                logging.debug(f"Extracted {len(transactions)} transactions from page {page_num}")
            else:
                logging.warning(f"No transactions found on page {page_num}")

        if not all_transactions:
            logging.error("No transactions could be extracted from any page")
            return []

        logging.info(f"Successfully extracted {len(all_transactions)} transactions total")
        return all_transactions

    except Exception as e:
        logging.error(f"Error processing image-based PDF: {str(e)}")
        return []

def process_mixed_content_pdf(pdf_path: str, page_types: List[str]) -> List[Dict]:
    """
    Process a PDF with mixed content types, handling each page appropriately.
    """
    try:
        logging.info(f"Processing mixed-content PDF: {pdf_path}")
        all_transactions = []

        # Open PDF file
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            images = convert_from_path(pdf_path)

            # Process each page according to its type
            for page_num, (page_type, image) in enumerate(zip(page_types, images)):
                logging.debug(f"Processing page {page_num + 1} as {page_type}")
                page_transactions = []

                if page_type == 'text':
                    # Use tabula for text-based extraction
                    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
                        # Create single-page PDF
                        writer = PyPDF2.PdfWriter()
                        writer.add_page(pdf_reader.pages[page_num])
                        writer.write(temp_pdf)
                        temp_pdf.close()

                        # Extract using tabula
                        tables = tabula.read_pdf(
                            temp_pdf.name,
                            pages=1,
                            multiple_tables=False,
                            guess=True,
                            lattice=False,
                            stream=True,
                            pandas_options={'header': None}
                        )

                        if tables:
                            for table in tables:
                                if len(table.columns) >= 4:
                                    table.columns = range(len(table.columns))
                                    page_transactions.extend(process_transaction_rows(table, page_num))

                        os.unlink(temp_pdf.name)

                else:  # 'image' or 'mixed'
                    # Use OCR-based extraction
                    page_transactions = extract_table_data(image)

                if page_transactions:
                    all_transactions.extend(page_transactions)
                    logging.debug(f"Extracted {len(page_transactions)} transactions from page {page_num + 1}")
                else:
                    logging.warning(f"No transactions found on page {page_num + 1}")

        if not all_transactions:
            logging.error("No transactions could be extracted from PDF")
            return []

        logging.info(f"Successfully extracted {len(all_transactions)} total transactions")
        return all_transactions

    except Exception as e:
        logging.error(f"Error processing mixed-content PDF: {str(e)}")
        return []

def process_transaction_rows(table, page_num):
    transactions = []
    for index, row in table.iterrows():
        transaction = {
            'Date': str(row[0]),
            'Transaction Details': str(row[1]),
            'Withdrawals ($)': str(row[2]),
            'Deposits ($)': str(row[3]),
            'Balance ($)': str(row[4]) if len(row) > 4 else ''
        }
        transactions.append(transaction)
    return transactions