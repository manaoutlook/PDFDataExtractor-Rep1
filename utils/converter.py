import logging
import tempfile
import pandas as pd
import tabula
import os
from datetime import datetime
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from .image_processor import is_image_based_pdf, process_image_based_pdf

logging.basicConfig(level=logging.DEBUG)

def clean_amount(amount_str):
    """Clean and format amount strings"""
    try:
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
    except Exception:
        return ''

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
    try:
        processed_data = []
        current_buffer = []

        # Clean the table
        table = table.dropna(how='all').reset_index(drop=True)

        logging.debug(f"Processing table on page {page_idx + 1}")
        logging.debug(f"Table shape: {table.shape}")
        logging.debug(f"Table columns: {table.columns}")
        logging.debug(f"First few rows:\n{table.head()}")

        # Identify columns based on headers
        header_row = None
        for idx, row in table.iterrows():
            row_text = ' '.join(str(val).upper() for val in row if not pd.isna(val))
            if any(keyword in row_text for keyword in ['DATE', 'TRANSACTION', 'AMOUNT', 'BALANCE']):
                header_row = idx
                break

        if header_row is not None:
            # Skip header row
            table = table.iloc[header_row + 1:].reset_index(drop=True)

        # Process each row
        for idx, row in table.iterrows():
            row_values = [str(val).strip() if not pd.isna(val) else '' for val in row]

            # Skip empty rows
            if not any(row_values):
                continue

            # Try to identify transaction components
            date = ''
            details = []
            withdrawal = ''
            deposit = ''
            balance = ''

            for col_idx, value in enumerate(row_values):
                if not value:
                    continue

                # First non-empty column usually contains the date
                if not date and any(char.isdigit() for char in value):
                    date = value
                    continue

                # Check if value looks like an amount
                if value.replace('.', '').replace(',', '').replace('-', '').replace('$', '').isdigit():
                    # Last amount is usually balance
                    if not balance:
                        balance = clean_amount(value)
                    # Earlier amounts are withdrawals/deposits
                    elif not withdrawal:
                        withdrawal = clean_amount(value)
                    elif not deposit:
                        deposit = clean_amount(value)
                else:
                    # Non-amount values are probably transaction details
                    details.append(value)

            if date or details:
                transaction = {
                    'Date': date,
                    'Transaction Details': ' '.join(details),
                    'Withdrawals ($)': withdrawal,
                    'Deposits ($)': deposit,
                    'Balance ($)': balance,
                    '_page_idx': page_idx,
                    '_row_idx': idx
                }
                processed_data.append(transaction)
                logging.debug(f"Extracted transaction: {transaction}")

        return processed_data

    except Exception as e:
        logging.error(f"Error processing rows: {str(e)}")
        return []

def convert_pdf_to_data(pdf_path: str, force_text_based: bool = False):
    """Extract data from PDF bank statement and return as list of dictionaries"""
    try:
        logging.info(f"Starting data extraction from {pdf_path}")

        if not os.path.exists(pdf_path):
            logging.error("PDF file not found")
            return None

        # Detect if PDF is image-based
        is_image_pdf = is_image_based_pdf(pdf_path, force_text_based)
        logging.info(f"PDF type detected: {'image-based' if is_image_pdf else 'text-based'}")

        if is_image_pdf:
            # Process image-based PDF
            transactions = process_image_based_pdf(pdf_path)
        else:
            # Process text-based PDF
            java_options = ['-Djava.awt.headless=true', '-Dfile.encoding=UTF8']

            # Try different extraction methods
            tables = []

            # Method 1: Stream mode with full page area
            tables = tabula.read_pdf(
                pdf_path,
                pages='all',
                multiple_tables=True,
                guess=True,
                stream=True,
                lattice=False,
                pandas_options={'header': None},
                java_options=java_options,
                area=[0, 0, 100, 100],
                relative_area=True
            )

            # Method 2: Try lattice mode if stream mode failed
            if not tables:
                logging.debug("Stream mode failed, trying lattice mode")
                tables = tabula.read_pdf(
                    pdf_path,
                    pages='all',
                    multiple_tables=True,
                    guess=True,
                    stream=False,
                    lattice=True,
                    pandas_options={'header': None},
                    java_options=java_options
                )

            # Method 3: Try without table detection
            if not tables:
                logging.debug("Lattice mode failed, trying without table detection")
                tables = tabula.read_pdf(
                    pdf_path,
                    pages='all',
                    multiple_tables=False,
                    guess=False,
                    stream=True,
                    pandas_options={'header': None},
                    java_options=java_options
                )

            if not tables:
                logging.error("No tables extracted from PDF")
                return None

            logging.debug(f"Extracted {len(tables)} tables from PDF")

            transactions = []
            seen_transactions = set()

            # Process each table
            for page_idx, table in enumerate(tables):
                if len(table.columns) < 2:  # Skip tables with too few columns
                    continue

                page_transactions = process_transaction_rows(table, page_idx)

                # Add unique transactions
                for trans in page_transactions:
                    trans_key = (
                        trans['Date'],
                        trans['Transaction Details'],
                        trans['Withdrawals ($)'],
                        trans['Deposits ($)'],
                        trans['Balance ($)']
                    )

                    if trans_key not in seen_transactions:
                        seen_transactions.add(trans_key)
                        transactions.append(trans)
                        logging.debug(f"Added transaction: {trans}")

        if not transactions:
            logging.error("No transactions extracted")
            return None

        logging.info(f"Successfully extracted {len(transactions)} transactions")
        return transactions

    except Exception as e:
        logging.error(f"Error in data extraction: {str(e)}")
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