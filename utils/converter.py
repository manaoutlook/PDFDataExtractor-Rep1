import logging
import tempfile
import pandas as pd
import tabula
import os
import pytesseract
from pdf2image import convert_from_path
from datetime import datetime
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

def clean_amount(amount_str):
    """Clean and format amount strings"""
    if pd.isna(amount_str):
        return ''
    try:
        # Remove currency symbols and cleanup
        amount_str = str(amount_str).replace('$', '').replace(',', '').strip()
        # Handle brackets for negative numbers
        if '(' in amount_str and ')' in amount_str:
            amount_str = '-' + amount_str.replace('(', '').replace(')', '')
        try:
            # Try to convert to float to validate
            float(amount_str)
            return amount_str
        except ValueError:
            return ''
    except Exception as e:
        logging.debug(f"Error cleaning amount {amount_str}: {str(e)}")
        return ''

def parse_date(date_str):
    """Parse date string from bank statement format"""
    try:
        if not date_str or pd.isna(date_str):
            return None

        date_str = str(date_str).strip().upper()

        # Skip rows that aren't dates
        if any(word in date_str for word in ['TOTALS', 'BALANCE', 'OPENING', 'PAGE', 'DATE']):
            return None

        # Handle various date formats
        parts = date_str.split()

        # Look for patterns like "26 APR" or "26 APR 2024"
        if len(parts) >= 2:
            try:
                # Extract day and month
                try:
                    day = int(''.join(filter(str.isdigit, parts[0])))
                except ValueError:
                    return None

                # Find month in the parts
                month = None
                for part in parts[1:]:
                    if part[:3] in ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 
                                  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']:
                        month = part[:3]
                        break

                if month and 1 <= day <= 31:
                    current_year = datetime.now().year
                    date_str = f"{day:02d} {month} {current_year}"
                    return datetime.strptime(date_str, '%d %b %Y')
            except (ValueError, IndexError) as e:
                logging.debug(f"Error parsing date {date_str}: {str(e)}")
                return None

        return None
    except Exception as e:
        logging.debug(f"Failed to parse date: {date_str}, error: {str(e)}")
        return None

def extract_text_based_data(pdf_path):
    """Extract data from text-based PDF using tabula"""
    try:
        tables = tabula.read_pdf(
            pdf_path,
            pages='all',
            multiple_tables=True,
            guess=True,
            lattice=False,
            stream=True,
            pandas_options={'header': None},
            java_options=['-Djava.awt.headless=true', '-Dfile.encoding=UTF8']
        )

        if not tables:
            logging.error("No tables found in text-based PDF")
            return None

        all_transactions = []
        seen_transactions = set()

        for page_idx, table in enumerate(tables):
            if len(table.columns) >= 4:
                table.columns = range(len(table.columns))
                transactions = process_transaction_rows(table, page_idx)

                for trans in transactions:
                    trans_key = (
                        trans['Date'],
                        trans['Transaction Details'],
                        str(trans['Withdrawals ($)']),
                        str(trans['Deposits ($)']),
                        str(trans['Balance ($)'])
                    )

                    if trans_key not in seen_transactions:
                        seen_transactions.add(trans_key)
                        all_transactions.append(trans)

        return all_transactions if all_transactions else None

    except Exception as e:
        logging.error(f"Error in text-based extraction: {str(e)}")
        return None

def extract_text_from_image(image):
    """Extract text from image using OCR"""
    try:
        # Configure tesseract for better accuracy with financial documents
        custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,$()-/ "'
        text = pytesseract.image_to_string(image, config=custom_config)
        logging.debug(f"Extracted OCR text: {text[:200]}...")  # Log first 200 chars
        return text
    except Exception as e:
        logging.error(f"OCR extraction error: {str(e)}")
        return None

def process_ocr_text(text):
    """Process OCR extracted text into structured data"""
    try:
        if not text:
            return None

        transactions = []
        lines = text.split('\n')
        current_transaction = None

        logging.debug(f"Processing {len(lines)} lines of OCR text")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            logging.debug(f"Processing line: {line}")

            # Try to parse as date
            date = parse_date(line)
            if date:
                logging.debug(f"Found date: {date}")
                # Save previous transaction if exists
                if current_transaction:
                    transactions.append(current_transaction)
                    logging.debug(f"Added transaction: {current_transaction}")

                # Start new transaction
                current_transaction = {
                    'Date': date.strftime('%d %b'),
                    'Transaction Details': '',
                    'Withdrawals ($)': '',
                    'Deposits ($)': '',
                    'Balance ($)': ''
                }
                continue

            if current_transaction:
                # Try to extract amounts
                amounts = []
                parts = line.split()
                for part in parts:
                    # Clean up the amount string
                    clean_part = part.replace('$', '').replace(',', '').strip()
                    # Check for amount patterns
                    if ('$' in part or '.' in clean_part) and any(c.isdigit() for c in clean_part):
                        try:
                            # Handle negative amounts in parentheses
                            if '(' in clean_part and ')' in clean_part:
                                clean_part = '-' + clean_part.replace('(', '').replace(')', '')
                            # Validate as float
                            float(clean_part)
                            amounts.append(clean_part)
                        except ValueError:
                            continue

                logging.debug(f"Found amounts in line: {amounts}")

                if amounts:
                    # Assume last amount is balance if multiple amounts found
                    if len(amounts) > 1:
                        if not current_transaction['Balance ($)']:
                            current_transaction['Balance ($)'] = amounts[-1]
                        if not current_transaction['Withdrawals ($)'] and float(amounts[0]) < 0:
                            current_transaction['Withdrawals ($)'] = str(abs(float(amounts[0])))
                        elif not current_transaction['Deposits ($)'] and float(amounts[0]) > 0:
                            current_transaction['Deposits ($)'] = amounts[0]
                    else:
                        # Single amount - add to transaction details
                        current_transaction['Transaction Details'] += f" {line}"
                else:
                    # Add to transaction details if no amounts found
                    if current_transaction['Transaction Details']:
                        current_transaction['Transaction Details'] += f" {line}"
                    else:
                        current_transaction['Transaction Details'] = line

        # Add last transaction
        if current_transaction:
            transactions.append(current_transaction)
            logging.debug(f"Added final transaction: {current_transaction}")

        logging.info(f"Extracted {len(transactions)} transactions from OCR text")
        return transactions if transactions else None

    except Exception as e:
        logging.error(f"Error processing OCR text: {str(e)}")
        return None

def extract_image_based_data(pdf_path):
    """Extract data from image-based PDF using OCR"""
    try:
        logging.info("Converting PDF to images for OCR processing")
        # Use higher DPI and optimize for text
        images = convert_from_path(
            pdf_path, 
            dpi=300,
            grayscale=True,
            thread_count=2
        )
        logging.info(f"Converted PDF to {len(images)} images")

        all_transactions = []

        for i, image in enumerate(images):
            logging.info(f"Processing page {i+1} with OCR")
            text = extract_text_from_image(image)
            if text:
                transactions = process_ocr_text(text)
                if transactions:
                    all_transactions.extend(transactions)
                    logging.info(f"Found {len(transactions)} transactions on page {i+1}")
                else:
                    logging.warning(f"No transactions found on page {i+1}")

        if not all_transactions:
            logging.error("No transactions could be extracted from any page")
            return None

        return all_transactions

    except Exception as e:
        logging.error(f"Error in image-based extraction: {str(e)}")
        return None

def convert_pdf_to_data(pdf_path: str, pdf_type: str = 'text'):
    """Extract data from PDF bank statement based on type"""
    try:
        logging.info(f"Starting data extraction from {pdf_path} using {pdf_type} method")

        if not os.path.exists(pdf_path):
            logging.error("PDF file not found")
            return None

        if pdf_type == 'text':
            data = extract_text_based_data(pdf_path)
        else:  # image
            data = extract_image_based_data(pdf_path)

        if data:
            logging.info(f"Successfully extracted {len(data)} transactions")
            return data
        else:
            logging.error("No transactions could be extracted from the PDF")
            return None

    except Exception as e:
        logging.error(f"Error in data extraction: {str(e)}")
        return None

def convert_pdf(pdf_path: str, output_format: str = 'excel', pdf_type: str = 'text'):
    """Convert PDF bank statement to Excel/CSV"""
    try:
        # Extract data using the appropriate method
        processed_data = convert_pdf_to_data(pdf_path, pdf_type)

        if not processed_data:
            return None

        # Convert to DataFrame
        df = pd.DataFrame(processed_data)

        # Create output file
        temp_file = tempfile.NamedTemporaryFile(delete=False)

        if output_format == 'excel':
            output_path = f"{temp_file.name}.xlsx"
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Transactions')
                workbook = writer.book
                worksheet = writer.sheets['Transactions']

                # Format headers
                header_font = Font(bold=True)
                header_fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
                header_alignment = Alignment(horizontal='center')

                for col in range(len(df.columns)):
                    cell = worksheet.cell(row=1, column=col+1)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment

                # Adjust column widths
                for idx, column in enumerate(worksheet.columns, 1):
                    max_length = max(len(str(cell.value)) for cell in column)
                    adjusted_width = (max_length + 2)
                    worksheet.column_dimensions[get_column_letter(idx)].width = adjusted_width

                # Set wrap text for transaction details
                for cell in worksheet['B']:
                    cell.alignment = Alignment(wrapText=True)
        else:
            output_path = f"{temp_file.name}.csv"
            df.to_csv(output_path, index=False)

        logging.info(f"Successfully created output file: {output_path}")
        return output_path

    except Exception as e:
        logging.error(f"Error in conversion: {str(e)}")
        return None

def process_transaction_rows(table, page_idx):
    """Process rows and handle multi-line transactions"""
    processed_data = []
    current_buffer = []

    # Clean the table
    table = table.dropna(how='all').reset_index(drop=True)

    def process_buffer():
        if not current_buffer:
            return None

        # Get date from first row
        date = parse_date(current_buffer[0][0])
        if not date:
            return None

        # Initialize transaction
        transaction = {
            'Date': date.strftime('%d %b'),
            'Transaction Details': '',
            'Withdrawals ($)': '',
            'Deposits ($)': '',
            'Balance ($)': ''
        }

        # Process all rows
        details = []
        for row in current_buffer:
            # Add description
            if row[1].strip():
                details.append(row[1].strip())

            # Process amounts
            withdrawal = clean_amount(row[2])
            deposit = clean_amount(row[3])
            balance = clean_amount(row[4]) if len(row) > 4 else ''

            # Update amounts if not already set
            if withdrawal and not transaction['Withdrawals ($)']:
                transaction['Withdrawals ($)'] = withdrawal
            if deposit and not transaction['Deposits ($)']:
                transaction['Deposits ($)'] = deposit
            if balance and not transaction['Balance ($)']:
                transaction['Balance ($)'] = balance

        # Join details
        transaction['Transaction Details'] = '\n'.join(filter(None, details))
        return transaction

    # Process each row
    for idx, row in table.iterrows():
        # Clean row values
        row_values = [str(val).strip() if not pd.isna(val) else '' for val in row]

        # Skip header rows
        if any(header in row_values[1].upper() for header in [
            'TRANSACTION DETAILS', 'WITHDRAWALS', 'DEPOSITS', 'BALANCE',
            'OPENING', 'TOTALS AT END OF PAGE', 'TOTALS FOR PERIOD'
        ]):
            if current_buffer:
                trans = process_buffer()
                if trans:
                    processed_data.append(trans)
                current_buffer = []
            continue

        # Check for date and content
        has_date = bool(parse_date(row_values[0]))
        has_content = any(val.strip() for val in row_values[1:5])

        if has_date:
            # Process previous buffer if exists
            if current_buffer:
                trans = process_buffer()
                if trans:
                    processed_data.append(trans)
                current_buffer = []

            # Start new buffer
            current_buffer = [row_values]
        elif current_buffer and has_content:
            # Add to current buffer
            current_buffer.append(row_values)

    # Process final buffer
    if current_buffer:
        trans = process_buffer()
        if trans:
            processed_data.append(trans)

    return processed_data