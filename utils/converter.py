import PyPDF2
import pandas as pd
import tempfile
import logging
from typing import Optional
import openpyxl
import re

def convert_pdf(pdf_path: str, output_format: str = 'excel') -> Optional[str]:
    try:
        expected_headers = [
            'VIN', 'Make', 'Model', 'Year', 'Status', 'Location', 'Make Code', 'Drive Type'
        ]

        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            data_rows = []
            header_found = False
            current_row = []
            
            title = None
            summary_info = []
            
            for page in pdf_reader.pages:
                text = page.extract_text()
                lines = [line.strip() for line in text.split('\n') if line.strip()]

                for line in lines:
                    # Extract title and date
                    if 'Vehicles Inventory Report' in line:
                        title = line.strip()
                        continue
                    
                    # Extract summary information using more specific patterns
                    if any(pattern in line for pattern in ['Total Vehicles:', 'Active Vehicles:', 'Vehicles in Maintenance:']):
                        cleaned_line = ' '.join(line.split())  # Normalize spaces
                        summary_info.append(cleaned_line)
                        continue
                    
                    if not line.strip():
                        continue
                    
                    # Skip the header row itself
                    if 'VIN' in line and any(header in line for header in expected_headers):
                        header_found = True
                        continue

                    # Process data rows
                    if header_found:
                        logging.debug(f"Processing line: {line}")
                        
                        # Skip empty lines and known headers
                        if not line.strip() or any(header in line for header in expected_headers):
                            continue
                            
                        # Try to identify any potential data row
                        if re.search(r'[A-Z0-9]', line):  # Line contains alphanumeric characters
                            # Split the line by multiple spaces while preserving single spaces
                            parts = [p.strip() for p in re.split(r'\s{2,}', line) if p.strip()]
                            
                            if parts:
                                if current_row and len(current_row) > 0:
                                    logging.debug(f"Adding previous row: {current_row}")
                                    data_rows.append(current_row[:len(expected_headers)])
                                
                                current_row = parts
                                logging.debug(f"New row extracted: {current_row}")
                            
                            # Filter out any empty or whitespace-only entries
                            current_row = [col for col in current_row if col.strip()]

                        # Ensure row doesn't exceed header count
                        if len(current_row) > len(expected_headers):
                            current_row = current_row[:len(expected_headers)]

            # Add the last row if exists
            if current_row:
                data_rows.append(current_row[:len(expected_headers)])

            # Debug logging for extracted content
            logging.debug("=== Extracted Content ===")
            for page_num, page in enumerate(pdf_reader.pages):
                logging.debug(f"=== Page {page_num + 1} ===")
                page_text = page.extract_text()
                logging.debug(page_text)
                logging.debug("=" * 50)

            if not data_rows:
                logging.error("No data rows were extracted from the PDF.")
                return None

            # Log extracted rows for debugging
            logging.debug("=== Extracted Rows ===")
            for row in data_rows:
                logging.debug(f"Row: {row}")

            # Clean and organize the data
            clean_rows = []
            for row in data_rows:
                if len(row) > 0:  # Only process non-empty rows
                    # Pad or trim the row to match headers
                    padded_row = row + [''] * (len(expected_headers) - len(row))
                    clean_row = padded_row[:len(expected_headers)]
                    # Add all rows with non-empty VIN
                    if clean_row[0].strip():
                        clean_rows.append(clean_row)

            if not clean_rows:
                logging.error("No valid rows found after cleaning")
                return None

            df = pd.DataFrame(clean_rows, columns=expected_headers)
            # Remove any duplicate rows
            df = df.drop_duplicates(subset=['VIN'], keep='first')

            # Create temporary file for output
            temp_file = tempfile.NamedTemporaryFile(delete=False)

            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Vehicle Inventory', startrow=5)

                    workbook = writer.book
                    worksheet = writer.sheets['Vehicle Inventory']
                    
                    # Add title and summary information
                    # Add title with bold formatting
                    if title:
                        cell = worksheet.cell(row=1, column=1, value=title)
                        cell.font = openpyxl.styles.Font(bold=True, size=12)
                        
                    # Add summary information
                    for idx, info in enumerate(summary_info, start=2):
                        cell = worksheet.cell(row=idx, column=1, value=info)
                        cell.font = openpyxl.styles.Font(size=11)
                        
                    # Add empty row before table
                    worksheet.cell(row=4, column=1, value='')
                    
                    # Merge cells for title and summary info
                    worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(expected_headers))
                    for idx in range(2, 2 + len(summary_info)):
                        worksheet.merge_cells(start_row=idx, start_column=1, end_row=idx, end_column=len(expected_headers))

                    # Auto-adjust column widths
                    for column in worksheet.columns:
                        max_length = 0
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

            return output_path

    except Exception as e:
        logging.error(f"Conversion error: {str(e)}")
        return None