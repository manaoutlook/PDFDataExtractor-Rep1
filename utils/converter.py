import PyPDF2
import pandas as pd
import tempfile
import logging
import re
from datetime import datetime
import openpyxl

def extract_transaction_data(text: str):
    """Enhanced transaction extraction for ANZ statements"""
    transactions = []

    # Split into lines and remove empty ones
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    # More specific patterns for ANZ
    date_pattern = r'(\d{2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*(?:\d{2}|\d{4}))'
    amount_pattern = r'(?:\$\s*)((?:-|\()?[\d,]+\.?\d*\)?)'

    in_transaction_section = False

    for i, line in enumerate(lines):
        # Start capturing after "Opening Balance" or "Brought Forward"
        if any(x in line for x in ["OPENING BALANCE", "BROUGHT FORWARD"]):
            in_transaction_section = True
            continue

        if not in_transaction_section:
            continue

        # Stop if we hit closing balance
        if "CLOSING BALANCE" in line:
            break

        # Try to match a transaction line
        date_match = re.search(date_pattern, line)
        if date_match:
            # Extract amounts - looking for 2-3 numbers that could be debit/credit and balance
            amounts = re.findall(amount_pattern, line)
            if amounts:
                transaction = {
                    'Date': date_match.group(1).strip(),
                    'Description': '',
                    'Debit': '',
                    'Credit': '',
                    'Balance': ''
                }

                # Get description - text between date and first amount
                desc_start = date_match.end()
                desc_end = line.find('$', desc_start)
                if desc_end > desc_start:
                    transaction['Description'] = line[desc_start:desc_end].strip()

                # Process amounts
                if len(amounts) >= 2:
                    # Last amount is usually balance
                    balance = amounts[-1].replace(',', '')
                    transaction['Balance'] = balance.replace('(', '-').replace(')', '')

                    # Previous amount is transaction
                    amount = amounts[-2].replace(',', '')
                    if '(' in amount or '-' in amount:
                        transaction['Debit'] = amount.replace('(', '').replace(')', '').replace('-', '')
                    else:
                        transaction['Credit'] = amount

                transactions.append(transaction)

    return transactions

def convert_pdf(pdf_path: str, output_format: str = 'excel'):
    """Convert PDF bank statement to Excel/CSV"""
    try:
        logging.info(f"Starting conversion of {pdf_path}")

        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            all_text = ""

            # Extract text from all pages
            for page in reader.pages:
                all_text += page.extract_text() + "\n"

            # Extract transactions
            transactions = extract_transaction_data(all_text)

            if not transactions:
                logging.error("No transactions found")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(transactions)

            # Create output file
            temp_file = tempfile.NamedTemporaryFile(delete=False)

            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                df.to_excel(output_path, index=False)
            else:
                output_path = f"{temp_file.name}.csv"
                df.to_csv(output_path, index=False)

            return output_path

    except Exception as e:
        logging.error(f"Error in conversion: {str(e)}")
        return None