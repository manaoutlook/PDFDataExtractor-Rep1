import logging
import tempfile
import pandas as pd
import tabula
import os
from datetime import datetime
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from .image_processor import is_image_based_pdf, process_image_based_pdf
from .template_manager import TemplateManager
import PyPDF2
import re

# Set up detailed logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def parse_amount(amount_str):
    """Parse amount string with currency symbols and formatting"""
    try:
        if pd.isna(amount_str):
            return ''
        # Remove currency symbols and cleanup
        amount_str = str(amount_str).strip()
        # Remove currency symbols and commas
        amount_str = re.sub(r'[$,]', '', amount_str)
        # Handle brackets for negative numbers
        if '(' in amount_str and ')' in amount_str:
            amount_str = '-' + amount_str.replace('(', '').replace(')', '')
        # Convert to float to validate
        float(amount_str)
        return amount_str
    except ValueError:
        logger.debug(f"Failed to parse amount: {amount_str}")
        return ''

def parse_date(date_str):
    """Parse date string from bank statement format"""
    try:
        if not date_str or pd.isna(date_str):
            return None

        date_str = str(date_str).strip().upper()

        # Skip rows that aren't dates
        if any(word in date_str.upper() for word in ['TOTALS', 'BALANCE', 'OPENING', 'CLOSING', 'BROUGHT', 'CARRIED']):
            return None

        # Handle different date formats
        date_patterns = [
            # "26 APR 2023", "26 APR", "26APR", "26 APRIL", "26APRIL" formats
            (r'(\d{1,2})\s*([A-Za-z]{3,})', '%d %b %Y'),
            # "26/04/2023", "26-04-2023" formats
            (r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', '%d/%m/%Y'),
            # "2023-04-26" format
            (r'(\d{4})-(\d{1,2})-(\d{1,2})', '%Y-%m-%d'),
            # RBS specific format: "26APR23"
            (r'(\d{1,2})([A-Za-z]{3})(\d{2})', '%d%b%y')
        ]

        # Clean the date string
        date_str = re.sub(r'\s+', ' ', date_str).strip()

        for pattern, date_format in date_patterns:
            match = re.match(pattern, date_str)
            if match:
                try:
                    if len(match.groups()) == 2:  # Day-Month format
                        day = int(match.group(1))
                        month = match.group(2)[:3]  # Take first 3 chars of month name
                        current_year = datetime.now().year
                        date_str = f"{day:02d} {month} {current_year}"
                        return datetime.strptime(date_str, '%d %b %Y')
                    elif len(match.groups()) == 3:  # Full date format
                        if date_format == '%d%b%y':  # RBS specific format
                            day = match.group(1)
                            month = match.group(2)
                            year = match.group(3)
                            date_str = f"{day}{month}20{year}"
                            return datetime.strptime(date_str, '%d%b%Y')
                        else:
                            # Normalize separators
                            normalized_date = re.sub(r'[/-]', '/', date_str)
                            parts = normalized_date.split('/')

                            # Handle 2-digit year
                            if len(parts[2]) == 2:
                                parts[2] = '20' + parts[2]

                            return datetime.strptime('/'.join(parts), date_format)
                except (ValueError, IndexError) as e:
                    logging.debug(f"Date parse error: {e} for {date_str}")
                    continue

        return None

    except Exception as e:
        logging.debug(f"Failed to parse date: {date_str}, error: {str(e)}")
        return None


def convert_pdf_to_data(pdf_path: str):
    """Extract data from PDF bank statement and return as list of dictionaries"""
    try:
        logger.info(f"Starting data extraction from {pdf_path}")

        if not os.path.exists(pdf_path):
            logger.error("PDF file not found")
            return None

        # Extract text for template matching
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text_content = ''
            for page_num, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                text_content += page_text
                logger.info(f"Page {page_num + 1} text sample:\n{page_text[:200]}")

        # Find matching template
        template_manager = TemplateManager()
        template = template_manager.find_matching_template(text_content)

        if template:
            logger.info(f"Using template: {template.name}")
            # Configure extraction parameters based on template
            if template.name == "ANZ_Personal":
                tables = tabula.read_pdf(
                    pdf_path,
                    pages='all',
                    multiple_tables=True,
                    guess=False,
                    lattice=False,
                    stream=True,
                    area=[150, 50, 750, 550],
                    relative_area=False,
                    pandas_options={'header': None}
                )
            else:  # Default to RBS parameters
                tables = tabula.read_pdf(
                    pdf_path,
                    pages='all',
                    multiple_tables=True,
                    guess=False,
                    lattice=False,
                    stream=True,
                    columns=[70, 250, 350, 450, 550],
                    area=[150, 50, 750, 550],
                    relative_area=False,
                    pandas_options={'header': None}
                )
        else:
            logger.warning("No template matched, using default extraction")
            tables = tabula.read_pdf(
                pdf_path,
                pages='all',
                multiple_tables=True,
                stream=True,
                pandas_options={'header': None}
            )

        if not tables:
            logger.error("No tables extracted from PDF")
            return None

        logger.info(f"Extracted {len(tables)} tables")
        transactions = []
        seen_transactions = set()

        for page_idx, table in enumerate(tables):
            logger.info(f"\nProcessing table on page {page_idx + 1}")
            logger.info(f"Table shape: {table.shape}")
            logger.info(f"First few rows:\n{table.head()}")

            if len(table.columns) < 4:
                logger.warning(f"Insufficient columns in table: {len(table.columns)}")
                continue

            # Clean the table
            table = table.dropna(how='all').reset_index(drop=True)
            table = table.fillna('')

            # Process each row
            for idx, row in table.iterrows():
                try:
                    # Skip header/footer rows
                    if any(skip in str(row[0]).upper() for skip in [
                        'DATE', 'BALANCE', 'OPENING', 'CLOSING', 'PAGE', 'STATEMENT'
                    ]):
                        continue

                    # Extract date
                    date = parse_date(str(row[0]))
                    if not date:
                        continue

                    # Extract transaction details based on template
                    if template and template.name == "ANZ_Personal":
                        transaction = {
                            'Date': date.strftime('%d %b'),
                            'Transaction Details': str(row[1]).strip(),
                            'Withdrawals ($)': parse_amount(row[2]),
                            'Deposits ($)': parse_amount(row[3]),
                            'Balance ($)': parse_amount(row[4]) if len(row) > 4 else ''
                        }
                    else:  # RBS format
                        transaction = {
                            'Date': date.strftime('%d %b'),
                            'Transaction Details': str(row[1]).strip(),
                            'Withdrawals ($)': parse_amount(row[2]),
                            'Deposits ($)': parse_amount(row[3]),
                            'Balance ($)': parse_amount(row[4]) if len(row) > 4 else ''
                        }

                    # Add transaction if it's unique
                    trans_key = (
                        transaction['Date'],
                        transaction['Transaction Details'],
                        transaction['Withdrawals ($)'],
                        transaction['Deposits ($)'],
                        transaction['Balance ($)']
                    )

                    if trans_key not in seen_transactions and any([
                        transaction['Withdrawals ($)'],
                        transaction['Deposits ($)']
                    ]):
                        seen_transactions.add(trans_key)
                        transactions.append(transaction)
                        logger.debug(f"Added transaction: {transaction}")

                except Exception as e:
                    logger.error(f"Error processing row {idx}: {str(e)}")
                    continue

        if not transactions:
            logger.error("No transactions extracted from any page")
            return None

        logger.info(f"Successfully extracted {len(transactions)} transactions")
        return transactions

    except Exception as e:
        logger.error(f"Error in data extraction: {str(e)}")
        logger.exception("Stack trace:")
        return None

def test_rbs_extraction(table, page_idx=0):
    """Test function for debugging RBS statement extraction"""
    logger.info("Starting RBS extraction test")
    logger.info(f"Input table shape: {table.shape}")
    logger.info(f"Table columns: {table.columns}")
    logger.info("\nFirst few rows of input:")
    for idx, row in table.head().iterrows():
        logger.info(f"Row {idx}: {row.values}")

    # Clean and prepare table
    table = table.dropna(how='all').reset_index(drop=True)

    # Test date parsing
    for idx, row in table.iterrows():
        date_str = str(row[0]).strip()
        parsed_date = parse_date(date_str)
        logger.info(f"\nTesting date: '{date_str}'")
        logger.info(f"Parsed date: {parsed_date}")

        # Test RBS pattern cleaning
        if len(row) > 1:
            desc = str(row[1]).strip()
            logger.info(f"Original description: '{desc}'")
            # Test RBS transaction code removal
            cleaned_desc = re.sub(r'\b(TFR|DD|DR|CR|ATM|POS|BGC|DEB|SO)\b', '', desc).strip()
            logger.info(f"After removing transaction codes: '{cleaned_desc}'")
            # Test reference number removal
            final_desc = re.sub(r'\b\d{6,}\b', '', cleaned_desc).strip()
            logger.info(f"After removing reference numbers: '{final_desc}'")

    # Now try full row processing
    return process_transaction_rows(table, page_idx, template=template_manager.get_template('RBS_Personal'))

def process_transaction_rows(table, page_idx, template=None):
    """Process rows and handle multi-line transactions with optional template guidance"""
    try:
        processed_data = []
        current_buffer = []

        # Clean the table
        table = table.dropna(how='all').reset_index(drop=True)

        logger.debug(f"Starting to process table on page {page_idx} with {len(table)} rows")
        logger.debug(f"Table columns: {table.columns}")
        logger.debug(f"First few rows: {table.head()}")

        def process_buffer():
            if not current_buffer:
                return None

            logger.debug(f"Processing buffer with {len(current_buffer)} rows: {current_buffer}")

            # Get date from first row
            date = parse_date(current_buffer[0][0])
            if not date:
                logger.debug(f"Failed to parse date from: {current_buffer[0][0]}")
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
                # Process description with template-specific cleaning
                if template and template.name == 'RBS_Personal':
                    if row[1].strip():
                        # Clean description based on RBS patterns
                        cleaned_text = row[1].strip()
                        # Remove transaction codes
                        cleaned_text = re.sub(r'\b(TFR|DD|DR|CR|ATM|POS|BGC|DEB|SO)\b', ' ', cleaned_text)
                        # Remove reference numbers
                        cleaned_text = re.sub(r'\b\d{6,}\b', '', cleaned_text)
                        # Remove multiple spaces
                        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
                        if cleaned_text:
                            details.append(cleaned_text)
                else:
                    # Default processing
                    if row[1].strip():
                        details.append(row[1].strip())

                # Process amounts with detailed logging
                withdrawal = parse_amount(row[2]) if len(row) > 2 else ''
                deposit = parse_amount(row[3]) if len(row) > 3 else ''
                balance = parse_amount(row[4]) if len(row) > 4 else ''

                logger.debug(f"Processing amounts - W: {withdrawal}, D: {deposit}, B: {balance}")

                # Update amounts if not already set
                if withdrawal and not transaction['Withdrawals ($)']:
                    transaction['Withdrawals ($)'] = withdrawal
                    logger.debug(f"Set withdrawal: {withdrawal}")
                if deposit and not transaction['Deposits ($)']:
                    transaction['Deposits ($)'] = deposit
                    logger.debug(f"Set deposit: {deposit}")
                if balance and not transaction['Balance ($)']:
                    transaction['Balance ($)'] = balance
                    logger.debug(f"Set balance: {balance}")

            # Join details
            transaction['Transaction Details'] = ' '.join(filter(None, details))
            logger.debug(f"Final transaction: {transaction}")
            return transaction

        # Process each row
        for idx, row in table.iterrows():
            # Clean row values
            row_values = [str(val).strip() if not pd.isna(val) else '' for val in row]

            logger.debug(f"Processing row {idx}: {row_values}")

            # Check for date and content
            has_date = bool(parse_date(row_values[0]))
            has_content = any(val.strip() for val in row_values[1:5])

            logger.debug(f"Row analysis - has_date: {has_date}, has_content: {has_content}")

            if has_date:
                # Process previous buffer if exists
                if current_buffer:
                    trans = process_buffer()
                    if trans:
                        processed_data.append(trans)
                        logger.debug(f"Added transaction from buffer: {trans}")
                    current_buffer = []

                # Start new buffer
                current_buffer = [row_values]
                logger.debug(f"Started new transaction: {row_values}")

            elif has_content and current_buffer:
                # Add to current buffer
                current_buffer.append(row_values)
                logger.debug(f"Added to current transaction: {row_values}")

        # Process final buffer
        if current_buffer:
            trans = process_buffer()
            if trans:
                processed_data.append(trans)
                logger.debug(f"Added final transaction: {trans}")

        logger.info(f"Successfully processed {len(processed_data)} transactions")
        return processed_data

    except Exception as e:
        logger.error(f"Error processing transactions: {str(e)}")
        return []


def convert_pdf(pdf_path: str, output_format: str = 'excel'):
    """Convert PDF bank statement to Excel/CSV"""
    try:
        # Extract data using the improved processing logic
        processed_data = convert_pdf_to_data(pdf_path)

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

        logger.info(f"Successfully created output file: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Error in conversion: {str(e)}")
        return None