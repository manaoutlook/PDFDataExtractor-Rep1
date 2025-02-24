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

# Add template manager to the module scope
template_manager = TemplateManager()

def clean_amount(amount_str):
    """Clean and format amount strings"""
    if pd.isna(amount_str):
        return ''
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

def process_transaction_rows(table, page_idx, template=None):
    """Process rows and handle multi-line transactions with optional template guidance"""
    try:
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
                'Date': date.strftime('%d %b'),
                'Transaction Details': '',
                'Withdrawals ($)': '',
                'Deposits ($)': '',
                'Balance ($)': '',
                '_page_idx': page_idx,
                '_row_idx': int(current_buffer[0][-1])
            }

            # Process all rows with template guidance if available
            details = []
            for row in current_buffer:
                if template and template.name == 'RBS_Personal':
                    # Special handling for RBS format
                    if row[1].strip():
                        # Clean description based on RBS patterns
                        cleaned_text = row[1].strip()
                        cleaned_text = re.sub(r'\b(TFR|DD|DR|CR|ATM|POS|BGC|DEB|SO)\b', ' ', cleaned_text).strip()
                        cleaned_text = re.sub(r'\b\d{6,}\b', '', cleaned_text).strip()
                        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()  # Normalize spaces
                        if cleaned_text:
                            details.append(cleaned_text)
                else:
                    # Default processing
                    if row[1].strip():
                        details.append(row[1].strip())

                # Process amounts with detailed logging
                withdrawal = clean_amount(row[2]) if len(row) > 2 else ''
                deposit = clean_amount(row[3]) if len(row) > 3 else ''
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
            transaction['Transaction Details'] = ' '.join(filter(None, details))
            logging.debug(f"Final transaction: {transaction}")
            return transaction

        # Process each row
        for idx, row in table.iterrows():
            # Clean row values and add index
            row_values = [str(val).strip() if not pd.isna(val) else '' for val in row]
            row_values.append(idx)

            logging.debug(f"Processing row {idx}: {row_values}")

            # Skip header rows with RBS-specific patterns
            if any(header in row_values[1].upper() for header in [
                'TRANSACTION DETAILS', 'WITHDRAWALS', 'DEPOSITS', 'BALANCE',
                'DESCRIPTION', 'DATE', 'TYPE', 'AMOUNT',
                'OPENING', 'TOTALS AT END OF PAGE', 'TOTALS FOR PERIOD',
                'BROUGHT FORWARD', 'CARRIED FORWARD', 'STATEMENT FROM', 'STATEMENT TO'
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
            has_content = any(val.strip() for val in row_values[1:5])

            logging.debug(f"Row analysis - has_date: {has_date}, has_content: {has_content}")

            if has_date:
                # Process previous buffer if exists
                if current_buffer:
                    trans = process_buffer()
                    if trans:
                        processed_data.append(trans)
                        logging.debug(f"Added transaction from buffer: {trans}")
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
                logging.debug(f"Added final transaction: {trans}")

        # Sort by page and row index
        processed_data.sort(key=lambda x: (x['_page_idx'], x['_row_idx']))

        # Remove tracking fields
        for trans in processed_data:
            trans.pop('_page_idx', None)
            trans.pop('_row_idx', None)

        logging.info(f"Successfully processed {len(processed_data)} transactions")
        return processed_data

    except Exception as e:
        logging.error(f"Error processing transactions: {str(e)}")
        return []

def test_rbs_extraction(table, page_idx=0):
    """Test function for debugging RBS statement extraction"""
    logging.info("Starting RBS extraction test")
    logging.info(f"Input table shape: {table.shape}")
    logging.info(f"Table columns: {table.columns}")
    logging.info("\nFirst few rows of input:")
    for idx, row in table.head().iterrows():
        logging.info(f"Row {idx}: {row.values}")

    # Clean and prepare table
    table = table.dropna(how='all').reset_index(drop=True)

    # Test date parsing
    for idx, row in table.iterrows():
        date_str = str(row[0]).strip()
        parsed_date = parse_date(date_str)
        logging.info(f"\nTesting date: '{date_str}'")
        logging.info(f"Parsed date: {parsed_date}")

        # Test RBS pattern cleaning
        if len(row) > 1:
            desc = str(row[1]).strip()
            logging.info(f"Original description: '{desc}'")
            # Test RBS transaction code removal
            cleaned_desc = re.sub(r'\b(TFR|DD|DR|CR|ATM|POS|BGC|DEB|SO)\b', '', desc).strip()
            logging.info(f"After removing transaction codes: '{cleaned_desc}'")
            # Test reference number removal
            final_desc = re.sub(r'\b\d{6,}\b', '', cleaned_desc).strip()
            logging.info(f"After removing reference numbers: '{final_desc}'")

    # Now try full row processing
    return process_transaction_rows(table, page_idx, template=template_manager.get_template('RBS_Personal'))

def convert_pdf_to_data(pdf_path: str):
    """Extract data from PDF bank statement and return as list of dictionaries"""
    try:
        logging.info(f"Starting data extraction from {pdf_path}")

        if not os.path.exists(pdf_path):
            logging.error("PDF file not found")
            return None

        # Extract raw text for template matching
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text_content = ''
            for page in pdf_reader.pages:
                text_content += page.extract_text()

            logging.info("Extracted text content sample:")
            logging.info(text_content[:500])  # Log first 500 chars for debugging

        # Find matching template
        template = template_manager.find_matching_template(text_content)
        if template:
            logging.info(f"Found matching template: {template.name}")
            logging.debug(f"Template patterns: {template.patterns}")
            logging.debug(f"Template layout: {template.layout}")

            # Configure tabula options based on template
            area = None
            if template.name == 'RBS_Personal':
                # Focus on the transaction area for RBS statements
                area = [10, 0, 100, 100]  # relative coordinates
                logging.info("Using RBS-specific extraction area")

        # Extract tables from PDF
        java_options = ['-Djava.awt.headless=true', '-Dfile.encoding=UTF8']
        logging.info("Starting table extraction with tabula")
        tables = tabula.read_pdf(
            pdf_path,
            pages='all',
            multiple_tables=True,
            guess=False,
            lattice=False,
            stream=True,
            area=area,
            relative_area=True if area else False,
            pandas_options={'header': None},
            java_options=java_options
        )

        if not tables:
            logging.error("No tables extracted from PDF")
            return None

        logging.info(f"Extracted {len(tables)} tables")
        transactions = []
        seen_transactions = set()

        for page_idx, table in enumerate(tables):
            logging.info(f"\nProcessing table on page {page_idx + 1}")
            logging.info(f"Table shape: {table.shape}")
            logging.info(f"Table columns: {table.columns}")
            logging.info(f"First few rows:\n{table.head()}")

            if len(table.columns) >= 4:
                table.columns = range(len(table.columns))

                # For RBS statements, use the test function first
                if template and template.name == 'RBS_Personal':
                    logging.info(f"\nTesting RBS extraction for page {page_idx + 1}")
                    page_transactions = test_rbs_extraction(table, page_idx)
                else:
                    page_transactions = process_transaction_rows(table, page_idx, template)

                # Add unique transactions
                for trans in page_transactions:
                    trans_key = (
                        trans['Date'],
                        trans['Transaction Details'],
                        str(trans['Withdrawals ($)']),
                        str(trans['Deposits ($)']),
                        str(trans['Balance ($)'])
                    )
                    if trans_key not in seen_transactions:
                        seen_transactions.add(trans_key)
                        transactions.append(trans)
                        logging.debug(f"Added transaction: {trans}")
            else:
                logging.warning(f"Table on page {page_idx + 1} has insufficient columns: {len(table.columns)}")

        if not transactions:
            logging.error("No transactions extracted")
            return None

        logging.info(f"Successfully extracted {len(transactions)} transactions")
        return transactions

    except Exception as e:
        logging.error(f"Error in data extraction: {str(e)}")
        logging.exception("Stack trace:")
        return None

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

        logging.info(f"Successfully created output file: {output_path}")
        return output_path

    except Exception as e:
        logging.error(f"Error in conversion: {str(e)}")
        return None