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
    return amount_str

def parse_date(date_str):
    """Parse date string from ANZ statement format"""
    try:
        if not date_str or pd.isna(date_str):
            return None

        date_str = str(date_str).strip().upper()

        # Skip rows that aren't dates
        if any(word in date_str for word in ['TOTALS', 'BALANCE']):
            return None

        # Handle day and month format (e.g., "26 APR")
        parts = date_str.split()
        if len(parts) == 2:
            try:
                day = int(parts[0])
                month = parts[1][:3]  # Take first 3 chars of month
                if month == 'APR' and day == 31:  # Handle special case
                    day = 30
                current_year = datetime.now().year
                date_str = f"{day:02d} {month} {current_year}"
                return datetime.strptime(date_str, '%d %b %Y')
            except (ValueError, IndexError) as e:
                logging.debug(f"Date parse error: {e} for {date_str}")
                return None

        return None
    except Exception as e:
        logging.debug(f"Failed to parse date: {date_str}, error: {str(e)}")
        return None

def process_transaction_rows(table):
    """Process rows and handle multi-line transactions"""
    processed_data = []
    current_transaction = None

    # Clean the table and skip if it's a header-only table
    table = table.dropna(how='all')
    table = table.reset_index(drop=True)

    # Skip if table contains only headers
    if len(table) <= 1:
        return []

    # Check for header rows and skip them
    if any(col.upper().strip() in ['TRANSACTION DETAILS', 'WITHDRAWALS ($)', 'DEPOSITS ($)', 'BALANCE ($)'] 
           for col in table.iloc[0] if isinstance(col, str)):
        table = table.iloc[1:]
        table = table.reset_index(drop=True)

    for idx, row in table.iterrows():
        # Convert row values to strings and clean
        row_values = [str(val).strip() if not pd.isna(val) else '' for val in row]

        logging.debug(f"Processing row {idx}: {row_values}")

        # Skip header rows
        if any(header in str(row_values[1]).upper() for header in 
               ['TRANSACTION DETAILS -WITHDRAWALS', 'TRANSACTION DETAILS', '-WITHDRAWALS', '-DEPOSITS', '-BALANCE']):
            logging.debug(f"Skipping header row: {row_values}")
            continue

        # Handle opening balance
        if 'OPENING BALANCE' in str(row_values[1]).upper():
            processed_data.append({
                'Date': row_values[0],
                'Transaction Details': 'OPENING BALANCE',
                'Withdrawals ($)': '',
                'Deposits ($)': '',
                'Balance ($)': clean_amount(row_values[4]) if len(row_values) > 4 else ''
            })
            continue

        # Handle totals rows but continue processing
        if any(total in str(row_values[1]).upper() for total in ['TOTALS AT END OF PERIOD', 'TOTALS AT END OF PAGE']):
            if current_transaction:
                processed_data.append(current_transaction)
                current_transaction = None
            continue

        # Parse date and monetary values
        date = parse_date(row_values[0])
        withdrawal = clean_amount(row_values[2])
        deposit = clean_amount(row_values[3])
        balance = clean_amount(row_values[4]) if len(row_values) > 4 else ''

        # Start a new transaction if we have a date
        if date:
            if current_transaction:
                processed_data.append(current_transaction)

            current_transaction = {
                'Date': date.strftime('%d %b'),
                'Transaction Details': row_values[1].strip(),
                'Withdrawals ($)': withdrawal,
                'Deposits ($)': deposit,
                'Balance ($)': balance
            }
        elif current_transaction and row_values[1].strip():
            # Handle continuation lines
            current_transaction['Transaction Details'] += f" {row_values[1].strip()}"
            if withdrawal:
                current_transaction['Withdrawals ($)'] = withdrawal
            if deposit:
                current_transaction['Deposits ($)'] = deposit
            if balance:
                current_transaction['Balance ($)'] = balance

    # Add the last transaction if it exists
    if current_transaction:
        processed_data.append(current_transaction)

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

        all_transactions = []
        seen_transactions = set()

        # Process each table
        for idx, table in enumerate(tables):
            logging.debug(f"Processing table {idx+1}, shape: {table.shape}")
            if len(table.columns) >= 4:
                table.columns = range(len(table.columns))
                transactions = process_transaction_rows(table)

                # Add unique transactions
                for trans in transactions:
                    # Create a more comprehensive transaction key
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
                    else:
                        logging.debug(f"Skipping duplicate transaction: {trans}")

        if not all_transactions:
            logging.error("No transactions extracted from tables")
            return None

        # Sort transactions by date and balance
        all_transactions.sort(key=lambda x: (
            datetime.strptime(x['Date'] + " 2025", '%d %b %Y') if x['Date'] else datetime.max,
            float(x['Balance ($)'].replace(',', '')) if x['Balance ($)'] else 0
        ))

        logging.info(f"Successfully extracted {len(all_transactions)} unique transactions")
        return all_transactions

    except Exception as e:
        logging.error(f"Error in data extraction: {str(e)}")
        return None

def convert_pdf(pdf_path: str, output_format: str = 'excel'):
    """Convert PDF bank statement to Excel/CSV using tabula-py"""
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