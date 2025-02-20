import PyPDF2
import pandas as pd
import tempfile
import logging
import re
from datetime import datetime
from typing import Optional, List, Dict
import openpyxl

def extract_transaction_data(text: str) -> List[Dict]:
    """
    Extract transaction data from text using regex patterns common in bank statements.
    Specifically enhanced for ANZ bank statements.
    """
    # Initialize transaction storage
    transactions = []

    # Enhanced date pattern for ANZ format
    date_pattern = r'\d{2}(?:\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s+)?(?:\d{2}|\d{4})?'

    # Enhanced amount pattern for ANZ format
    amount_pattern = r'-?(?:[\$\£\€]?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\(\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\))'

    # Split text into lines and process each line
    lines = text.split('\n')
    current_transaction = None

    logging.debug(f"Processing {len(lines)} lines of text")

    # Flag to indicate when we've reached the transaction section
    in_transaction_section = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        logging.debug(f"Processing line: {line}")

        # Check if we've reached the transaction section
        if "OPENING BALANCE" in line:
            in_transaction_section = True
            continue

        if not in_transaction_section:
            continue

        # Look for date at the start of line
        date_match = re.match(f"^{date_pattern}", line)

        if date_match:
            # If we have a previous transaction, save it
            if current_transaction:
                transactions.append(current_transaction)
                logging.debug(f"Saved transaction: {current_transaction}")

            # Extract date
            date_str = date_match.group().strip()
            logging.debug(f"Found date: {date_str}")

            # Start new transaction
            current_transaction = {
                'Date': date_str,
                'Description': '',
                'Debit': '',
                'Credit': '',
                'Balance': ''
            }

            # Remove date from line to process remaining parts
            remaining = line[len(date_str):].strip()

            # Find amounts in the remaining text
            amounts = re.findall(amount_pattern, remaining)

            if amounts:
                logging.debug(f"Found amounts: {amounts}")
                # Process description (text between date and first amount)
                desc_end = remaining.find(amounts[0])
                current_transaction['Description'] = remaining[:desc_end].strip()

                # Process amounts based on position
                if len(amounts) >= 2:  # We have both transaction amount and balance
                    last_amount = amounts[-1].replace('$', '').strip()  # Balance is always last
                    current_transaction['Balance'] = last_amount

                    # Transaction amount is the second-to-last if multiple amounts exist
                    transaction_amount = amounts[-2].replace('$', '').strip()
                    if transaction_amount.startswith('-') or transaction_amount.startswith('('):
                        current_transaction['Debit'] = transaction_amount.replace('(', '').replace(')', '')
                    else:
                        current_transaction['Credit'] = transaction_amount
            else:
                # No amounts found, treat entire remaining text as description
                current_transaction['Description'] = remaining

        elif current_transaction:
            # If line doesn't start with date, it might be continuation of description
            current_transaction['Description'] += ' ' + line

    # Add last transaction
    if current_transaction:
        transactions.append(current_transaction)
        logging.debug(f"Saved final transaction: {current_transaction}")

    logging.info(f"Extracted {len(transactions)} transactions")
    return transactions

def convert_pdf(pdf_path: str, output_format: str = 'excel') -> Optional[str]:
    """
    Convert PDF bank statement to Excel or CSV format with proper table structure preservation
    """
    try:
        logging.info(f"Starting conversion of {pdf_path}")

        # Read PDF
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            all_transactions = []

            # Process each page
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text = page.extract_text()
                logging.debug(f"Extracted text from page {page_num + 1}")

                # Extract transactions from the page
                page_transactions = extract_transaction_data(text)
                all_transactions.extend(page_transactions)

                logging.debug(f"Extracted {len(page_transactions)} transactions from page {page_num + 1}")

        if not all_transactions:
            logging.error("No transactions found in the document")
            return None

        # Convert to DataFrame
        df = pd.DataFrame(all_transactions)

        # Create temporary file for output
        temp_file = tempfile.NamedTemporaryFile(delete=False)

        if output_format == 'excel':
            output_path = f"{temp_file.name}.xlsx"
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Transactions')

                # Format the workbook
                workbook = writer.book
                worksheet = writer.sheets['Transactions']

                # Style for headers
                header_style = openpyxl.styles.NamedStyle(name='header')
                header_style.font = openpyxl.styles.Font(bold=True, size=12)
                header_style.fill = openpyxl.styles.PatternFill(
                    start_color="CCE5FF",
                    end_color="CCE5FF",
                    fill_type="solid"
                )

                # Apply header style
                for col in range(1, len(df.columns) + 1):
                    cell = worksheet.cell(row=1, column=col)
                    cell.style = header_style

                # Auto-adjust column widths
                for column in worksheet.columns:
                    max_length = 0
                    column = [cell for cell in column]
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = (max_length + 2)
                    worksheet.column_dimensions[column[0].column_letter].width = adjusted_width
        else:
            output_path = f"{temp_file.name}.csv"
            df.to_csv(output_path, index=False)

        logging.info(f"Successfully converted to {output_format}")
        return output_path

    except Exception as e:
        logging.error(f"Conversion error: {str(e)}")
        return None