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
            
            for page in pdf_reader.pages:
                text = page.extract_text()
                lines = [line.strip() for line in text.split('\n') if line.strip()]

                for line in lines:
                    # Skip summary lines and empty lines
                    if any(x in line.lower() for x in ['total vehicles:', 'active vehicles:', 'vehicles in maintenance:']) or not line.strip():
                        continue
                    
                    # Skip the header row itself
                    if 'VIN' in line and any(header in line for header in expected_headers):
                        header_found = True
                        continue

                    # Process data rows
                    if header_found:
                        # Match for VIN-like pattern at start of line
                        vin_match = re.match(r'^([A-Z0-9]{17}|[A-Z0-9]{6,}(?=\s))', line)
                        
                        if vin_match:
                            if current_row:
                                if len(current_row) > 0:  # Only add non-empty rows
                                    data_rows.append(current_row[:len(expected_headers)])
                            
                            # Split remaining line into columns
                            remaining = line[vin_match.end():].strip()
                            # Split by multiple spaces while preserving internal single spaces
                            parts = [p.strip() for p in re.split(r'\s{2,}', remaining)]
                            current_row = [vin_match.group(1)] + parts
                            
                            # Filter out any empty or whitespace-only entries
                            current_row = [col for col in current_row if col.strip()]

                        # Ensure row doesn't exceed header count
                        if len(current_row) > len(expected_headers):
                            current_row = current_row[:len(expected_headers)]

            # Add the last row if exists
            if current_row:
                data_rows.append(current_row[:len(expected_headers)])

            # Clean and organize the data
            clean_rows = []
            for row in data_rows:
                if len(row) > 0:  # Only process non-empty rows
                    # Pad or trim the row to match headers
                    padded_row = row + [''] * (len(expected_headers) - len(row))
                    clean_row = padded_row[:len(expected_headers)]
                    # Only add rows that have a valid VIN
                    if clean_row[0].strip() and len(clean_row[0].strip()) >= 6:
                        clean_rows.append(clean_row)

            df = pd.DataFrame(clean_rows, columns=expected_headers)
            # Remove any duplicate rows
            df = df.drop_duplicates(subset=['VIN'], keep='first')

            # Create temporary file for output
            temp_file = tempfile.NamedTemporaryFile(delete=False)

            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Vehicle Inventory')

                    workbook = writer.book
                    worksheet = writer.sheets['Vehicle Inventory']

                    # Format header row
                    for col in range(len(df.columns)):
                        cell = worksheet.cell(row=1, column=col + 1)
                        cell.fill = openpyxl.styles.PatternFill(
                            start_color="FFFF00",
                            end_color="FFFF00",
                            fill_type="solid"
                        )

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