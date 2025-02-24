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

        def process_buffer():
            if not current_buffer:
                return None

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

                # Process amounts
                withdrawal = clean_amount(row[2]) if len(row) > 2 else ''
                deposit = clean_amount(row[3]) if len(row) > 3 else ''
                balance = clean_amount(row[4]) if len(row) > 4 else ''

                logging.debug(f"Processing amounts - W: {withdrawal}, D: {deposit}, B: {balance}")

                # Update amounts if not already set
                if withdrawal and not transaction['Withdrawals ($)']:
                    transaction['Withdrawals ($)'] = withdrawal
                if deposit and not transaction['Deposits ($)']:
                    transaction['Deposits ($)'] = deposit
                if balance and not transaction['Balance ($)']:
                    transaction['Balance ($)'] = balance

            # Join details
            transaction['Transaction Details'] = '\n'.join(filter(None, details))
            logging.debug(f"Final transaction: {transaction}")
            return transaction

        # Process each row
        for idx, row in table.iterrows():
            # Clean row values and add index
            row_values = [str(val).strip() if not pd.isna(val) else '' for val in row]
            row_values.append(idx)

            # Skip header rows
            if any(header in ' '.join(row_values).upper() for header in [
                'TRANSACTION DETAILS', 'WITHDRAWALS', 'DEPOSITS', 'BALANCE',
                'OPENING', 'TOTALS', 'DATE'
            ]):
                if current_buffer:
                    trans = process_buffer()
                    if trans:
                        processed_data.append(trans)
                    current_buffer = []
                continue

            # Check for date and content
            has_date = any(char.isdigit() for char in row_values[0])
            has_content = any(val.strip() for val in row_values[1:])

            if has_date and has_content:
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

            # Process each table
            transactions = []
            seen_transactions = set()

            for page_idx, table in enumerate(tables):
                if len(table.columns) < 2:  # Skip tables with too few columns
                    continue

                table.columns = range(len(table.columns))  # Ensure numeric column names
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