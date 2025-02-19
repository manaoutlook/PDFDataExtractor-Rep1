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
                    # Skip summary lines
                    if any(x in line.lower() for x in ['total vehicles:', 'active vehicles:', 'vehicles in maintenance:']):
                        continue

                    # Detect header row more flexibly
                    if not header_found and 'VIN' in line:
                        header_found = True
                        continue

                    if header_found:
                        # More flexible VIN pattern - allow any alphanumeric sequence at start of line
                        vin_match = re.search(r'^([A-Za-z0-9]+\s*)', line)

                        if vin_match:
                            if current_row:
                                # Save previous row if exists
                                data_rows.append(current_row[:len(expected_headers)])

                            # Start new row with VIN
                            current_row = [vin_match.group(0)]

                            # Get remaining data from the line
                            remaining = line[vin_match.end():].strip()
                            parts = [p.strip() for p in remaining.split('  ') if p.strip()]
                            current_row.extend(parts)
                        elif current_row:
                            # Append to last column if it's continuation data
                            parts = [p.strip() for p in line.split('  ') if p.strip()]
                            current_row.extend(parts)

                        # Ensure row doesn't exceed header count
                        if len(current_row) > len(expected_headers):
                            current_row = current_row[:len(expected_headers)]

            # Add the last row if exists
            if current_row:
                data_rows.append(current_row[:len(expected_headers)])

            # Create DataFrame with proper column alignment
            clean_rows = []
            for row in data_rows:
                # Pad rows that are too short
                padded_row = row + [''] * (len(expected_headers) - len(row))
                clean_rows.append(padded_row[:len(expected_headers)])

            df = pd.DataFrame(clean_rows, columns=expected_headers)

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