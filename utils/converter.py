import logging
import tempfile
import pandas as pd
import tabula
import os
from datetime import datetime
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

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
                return parsed_date
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
            'Date': date.strftime('%d %b'),
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

    # Log results
    logging.debug(f"Processed {len(processed_data)} transactions")
    for idx, trans in enumerate(processed_data):
        logging.debug(f"Transaction {idx}: {trans}")

    return processed_data

def convert_pdf_to_data(pdf_path: str):
    """Extract data from PDF bank statement and return as list of dictionaries"""
    try:
        logging.info(f"Starting data extraction from {pdf_path}")

        if not os.path.exists(pdf_path):
            logging.error("PDF file not found")
            return None

        # Configure Java options for headless mode
        java_options = [
            '-Djava.awt.headless=true',
            '-Dfile.encoding=UTF8'
        ]

        # Extract tables from PDF
        logging.debug("Attempting to extract tables from PDF")
        tables = tabula.read_pdf(
            pdf_path,
            pages='all',
            multiple_tables=True,
            guess=True,
            lattice=False,
            stream=True,
            pandas_options={'header': None},
            java_options=java_options
        )

        if not tables:
            logging.error("No tables extracted from PDF")
            return None

        logging.debug(f"Extracted {len(tables)} tables from PDF")

        all_transactions = []
        seen_transactions = set()

        # Process each table
        for page_idx, table in enumerate(tables):
            logging.debug(f"Processing table {page_idx+1}, shape: {table.shape}")
            logging.debug(f"Table contents:\n{table}")

            if len(table.columns) >= 4:  # Ensure table has required columns
                table.columns = range(len(table.columns))
                transactions = process_transaction_rows(table, page_idx)

                # Add unique transactions
                for trans in transactions:
                    # Create a comprehensive transaction key
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
                        logging.debug(f"Added unique transaction: {trans}")
                    else:
                        logging.debug(f"Skipping duplicate transaction: {trans}")

        if not all_transactions:
            logging.error("No transactions extracted from tables")
            return None

        logging.info(f"Successfully extracted {len(all_transactions)} unique transactions")
        return all_transactions

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