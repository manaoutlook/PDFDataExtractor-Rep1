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
from datetime import datetime
import tabula
import pandas as pd

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

def parse_date(date_str):
    """Parse date string from bank statement format"""
    try:
        if not date_str or pd.isna(date_str):
            return None

        date_str = str(date_str).strip().upper()

        # Skip rows that aren't dates
        if any(word in date_str for word in ['TOTALS', 'BALANCE', 'OPENING']):
            return None

        # Handle day and month format (e.g., "26 APR")
        parts = date_str.split()
        if len(parts) == 2:
            try:
                day = int(parts[0])
                month = parts[1][:3]  # Take first 3 chars of month
                current_year = datetime.now().year
                # Handle special case for dates like "31 APR"
                if month == 'APR' and day == 31:
                    day = 30
                date_str = f"{day:02d} {month} {current_year}"
                parsed_date = datetime.strptime(date_str, '%d %b %Y')
                return parsed_date.strftime('%d %b')
            except (ValueError, IndexError) as e:
                logging.debug(f"Date parse error: {e} for {date_str}")
                return None

        return None
    except Exception as e:
        logging.debug(f"Failed to parse date: {date_str}, error: {str(e)}")
        return None

def process_transaction_rows(table, page_idx):
    """Process rows and handle multi-line transactions"""
    processed_data = []
    current_buffer = []

    # Clean the table
    table = table.dropna(how='all').reset_index(drop=True)

    logging.debug(f"Starting to process table on page {page_idx} with {len(table)} rows")
    logging.debug(f"Table columns: {table.columns}")
    logging.debug(f"First few rows: {table.head()}")

    def process_buffer():
        if not current_buffer:
            return None

        logging.debug(f"Processing buffer with {len(current_buffer)} rows: {current_buffer}")

        # Get date from first row
        date = parse_date(current_buffer[0][0])
        if not date:
            logging.debug(f"Failed to parse date from: {current_buffer[0][0]}")
            return None

        # Initialize transaction
        transaction = {
            'Date': date,
            'Transaction Details': '',
            'Withdrawals ($)': '',
            'Deposits ($)': '',
            'Balance ($)': '',
            '_page_idx': page_idx,
            '_row_idx': int(current_buffer[0][-1])
        }

        # Process all rows
        details = []
        for row in current_buffer:
            # Add description
            if row[1].strip():
                details.append(row[1].strip())
                logging.debug(f"Added description: {row[1].strip()}")

            # Process amounts with detailed logging
            withdrawal = clean_amount(row[2])
            deposit = clean_amount(row[3])
            balance = clean_amount(row[4]) if len(row) > 4 else ''

            logging.debug(f"Processing amounts - W: {withdrawal}, D: {deposit}, B: {balance}")

            # Update amounts if not already set
            if withdrawal and not transaction['Withdrawals ($)']:
                transaction['Withdrawals ($)'] = withdrawal
                logging.debug(f"Set withdrawal: {withdrawal}")
            if deposit and not transaction['Deposits ($)']:
                transaction['Deposits ($)'] = deposit
                logging.debug(f"Set deposit: {deposit}")
            if balance and not transaction['Balance ($)']:
                transaction['Balance ($)'] = balance
                logging.debug(f"Set balance: {balance}")

        # Join details
        transaction['Transaction Details'] = '\n'.join(filter(None, details))
        logging.debug(f"Final transaction: {transaction}")
        return transaction

    # Process each row
    for idx, row in table.iterrows():
        # Clean row values and add index
        row_values = [str(val).strip() if not pd.isna(val) else '' for val in row]
        row_values.append(idx)

        logging.debug(f"Processing row {idx}: {row_values}")

        # Skip header rows
        if any(header in row_values[1].upper() for header in [
            'TRANSACTION DETAILS', 'WITHDRAWALS', 'DEPOSITS', 'BALANCE',
            'OPENING', 'TOTALS AT END OF PAGE', 'TOTALS FOR PERIOD'
        ]):
            logging.debug(f"Skipping header row: {row_values}")
            if current_buffer:
                trans = process_buffer()
                if trans:
                    processed_data.append(trans)
                current_buffer = []
            continue

        # Check for date and content
        has_date = bool(parse_date(row_values[0]))
        has_content = any(val.strip() for val in row_values[1:5])  # Include amount columns in content check

        logging.debug(f"Row analysis - has_date: {has_date}, has_content: {has_content}")

        if has_date:
            # Process previous buffer if exists
            if current_buffer:
                trans = process_buffer()
                if trans:
                    processed_data.append(trans)
                current_buffer = []

            # Start new buffer
            current_buffer = [row_values]
            logging.debug(f"Started new transaction: {row_values}")

        elif current_buffer and has_content:
            # Add to current buffer
            current_buffer.append(row_values)
            logging.debug(f"Added to current transaction: {row_values}")

    # Process final buffer
    if current_buffer:
        trans = process_buffer()
        if trans:
            processed_data.append(trans)

    # Sort by page and row index
    processed_data.sort(key=lambda x: (x['_page_idx'], x['_row_idx']))

    # Remove tracking fields
    for trans in processed_data:
        trans.pop('_page_idx', None)
        trans.pop('_row_idx', None)

    return processed_data

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

        # Convert PDF pages to images with higher DPI for better quality
        images = convert_from_path(pdf_path, dpi=300)

        all_transactions = []
        for page_num, image in enumerate(images, 1):
            logging.debug(f"Processing page {page_num}")

            # Process the page using tabula-py since it's better at table structure detection
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
                # Save the current page as a temporary PDF
                image.save(temp_pdf.name, 'PDF')

                # Extract table from the temporary PDF
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
                    # Process each table using the existing transaction processing logic
                    for table in tables:
                        if len(table.columns) >= 4:
                            table.columns = range(len(table.columns))
                            page_transactions = process_transaction_rows(table, page_num)
                            if page_transactions:
                                all_transactions.extend(page_transactions)
                                logging.debug(f"Extracted {len(page_transactions)} transactions from page {page_num}")
                            else:
                                logging.warning(f"No valid transactions found in table on page {page_num}")
                else:
                    logging.warning(f"No tables found on page {page_num}")

                # Clean up temporary file
                os.unlink(temp_pdf.name)

        if not all_transactions:
            logging.error("No transactions could be extracted from any page")
            return []

        logging.info(f"Successfully extracted {len(all_transactions)} transactions total")
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