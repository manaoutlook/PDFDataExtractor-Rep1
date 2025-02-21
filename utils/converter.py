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
        # Clean and validate the date string
        if not date_str or pd.isna(date_str):
            return None

        date_str = str(date_str).strip().upper()

        # Skip header or footer text that contains these words
        if any(word in date_str.upper() for word in ['TOTALS']):
            return None

        # If it's just day and month (e.g., "26 APR"), add current year
        parts = date_str.split()
        if len(parts) == 2:
            try:
                day = int(parts[0])
                month = parts[1][:3]  # Take first 3 chars of month
                current_year = datetime.now().year
                date_str = f"{day:02d} {month} {current_year}"
                return datetime.strptime(date_str, '%d %b %Y')
            except (ValueError, IndexError):
                return None

        return None
    except Exception as e:
        logging.debug(f"Failed to parse date: {date_str}, error: {str(e)}")
        return None

def process_transaction_rows(table):
    """Process rows and handle multi-line transactions"""
    processed_data = []
    current_transaction = None

    # Drop any completely empty rows
    table = table.dropna(how='all')
    table = table.reset_index(drop=True)

    for idx, row in table.iterrows():
        # Clean row values
        row_values = [str(val).strip() if not pd.isna(val) else '' for val in row]

        logging.debug(f"Processing row {idx}: {row_values}")

        # Handle opening balance specially
        if 'OPENING BALANCE' in str(row_values[1]).upper():
            processed_data.append({
                'Date': row_values[0],
                'Transaction Details': row_values[1],
                'Withdrawals ($)': '',
                'Deposits ($)': '',
                'Balance ($)': clean_amount(row_values[4]) if len(row_values) > 4 else ''
            })
            logging.debug("Added opening balance row")
            continue

        # Skip totals rows
        if 'TOTALS AT END OF PERIOD' in str(row_values[1]).upper():
            logging.debug(f"Skipping totals row: {row_values}")
            continue

        # Check if this is a new transaction (has a date) or a continuation
        date = parse_date(row_values[0])
        has_monetary_value = any(clean_amount(val) for val in row_values[2:5] if val)

        if date or has_monetary_value:
            # If we have a pending transaction, add it
            if current_transaction:
                processed_data.append(current_transaction)
                logging.debug(f"Added pending transaction: {current_transaction}")

            # Create new transaction
            current_transaction = {
                'Date': date.strftime('%d %b') if date else current_transaction['Date'],
                'Transaction Details': row_values[1],
                'Withdrawals ($)': clean_amount(row_values[2]),
                'Deposits ($)': clean_amount(row_values[3]),
                'Balance ($)': clean_amount(row_values[4]) if len(row_values) > 4 else ''
            }
            logging.debug(f"Created new transaction: {current_transaction}")
        elif current_transaction and row_values[1].strip():
            # Append additional details to current transaction
            current_transaction['Transaction Details'] += f" {row_values[1].strip()}"

            # Update monetary values if present
            if clean_amount(row_values[2]):
                current_transaction['Withdrawals ($)'] = clean_amount(row_values[2])
            if clean_amount(row_values[3]):
                current_transaction['Deposits ($)'] = clean_amount(row_values[3])
            if len(row_values) > 4 and clean_amount(row_values[4]):
                current_transaction['Balance ($)'] = clean_amount(row_values[4])

            logging.debug(f"Updated transaction with continuation line: {current_transaction}")

    # Add the last transaction if pending
    if current_transaction:
        processed_data.append(current_transaction)
        logging.debug(f"Added final pending transaction: {current_transaction}")

    logging.debug(f"Total transactions processed: {len(processed_data)}")
    return processed_data

def convert_pdf_to_data(pdf_path: str):
    """Extract data from PDF bank statement and return as list of dictionaries"""
    try:
        logging.info(f"Starting data extraction from {pdf_path}")

        # File validation
        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
            logging.error("PDF file not found or empty")
            return None

        # Check Java availability
        try:
            import subprocess
            subprocess.run(['java', '-version'], capture_output=True, check=True)
        except Exception as e:
            logging.error(f"Java not available: {str(e)}")
            return None

        # Extract tables
        try:
            tables = tabula.read_pdf(
                pdf_path,
                pages='all',
                multiple_tables=True,
                guess=True,
                lattice=False,
                stream=True,
                pandas_options={'header': None},
                java_options=['-Dfile.encoding=UTF8', '-Djava.awt.headless=true']
            )
            if not isinstance(tables, list):
                tables = [tables]
            logging.info(f"Successfully extracted {len(tables)} tables from PDF")
        except Exception as e:
            logging.error(f"Error during PDF table extraction: {str(e)}")
            return None

        all_transactions = []

        # Process each table
        for idx, table in enumerate(tables):
            logging.debug(f"Processing table {idx+1}, shape: {table.shape}")
            logging.debug(f"Table contents:\n{table}")

            if len(table.columns) >= 4:  # Ensure table has enough columns
                table.columns = range(len(table.columns))

                # Process transactions with multi-line handling
                transactions = process_transaction_rows(table)
                all_transactions.extend(transactions)

        if not all_transactions:
            logging.error("No valid transactions found after processing")
            return None

        logging.info(f"Successfully processed {len(all_transactions)} transactions")
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

                # Auto-adjust column widths
                for idx, column in enumerate(worksheet.columns, 1):
                    max_length = 0
                    column = [cell for cell in column]
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = (max_length + 2)
                    worksheet.column_dimensions[get_column_letter(idx)].width = adjusted_width

                # Set wrap text for transaction details column
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