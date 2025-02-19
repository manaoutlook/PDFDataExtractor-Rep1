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
            # Initialize PDF reader
            pdf_reader = PyPDF2.PdfReader(file)
            data_rows = []
            title = None
            summary_info = []

            logging.debug(f"Processing PDF with {len(pdf_reader.pages)} pages")

            for page_num, page in enumerate(pdf_reader.pages):
                text = page.extract_text()
                logging.debug(f"Page {page_num + 1} text extracted: {text[:200]}...")  # Log first 200 chars

                # Process text line by line
                lines = text.split('\n')
                for line_num, line in enumerate(lines):
                    line = line.strip()
                    logging.debug(f"Processing line {line_num}: {line}")

                    if not line:
                        continue

                    # Extract title
                    if 'Vehicles Inventory Report' in line:
                        title = line
                        logging.debug(f"Found title: {title}")
                        continue

                    # Extract summary information
                    if any(x in line for x in ['Total Vehicles:', 'Active Vehicles:', 'Vehicles in Maintenance:']):
                        summary_info.append(line)
                        logging.debug(f"Found summary info: {line}")
                        continue

                    # Skip header row
                    if all(header in line for header in ['VIN', 'Make', 'Model']):
                        logging.debug("Skipping header row")
                        continue

                    # More flexible VIN pattern - at least 10 characters with mix of letters and numbers
                    potential_vins = re.finditer(r'[A-HJ-NPR-Z0-9]{10,}', line)

                    for match in potential_vins:
                        vin = match.group()
                        if len(vin) >= 10 and any(c.isalpha() for c in vin) and any(c.isdigit() for c in vin):
                            # Get the rest of the line after the VIN
                            rest_of_line = line[match.end():].strip()
                            row_data = [vin]  # Start with VIN

                            # Split remaining data and clean
                            remaining_fields = [f for f in rest_of_line.split() if f]
                            row_data.extend(remaining_fields)

                            # Only process rows that have enough data
                            if len(row_data) >= 3:  # At least VIN, Make, and Model
                                # Pad with empty strings if needed
                                while len(row_data) < len(expected_headers):
                                    row_data.append('')
                                # Trim if too long
                                row_data = row_data[:len(expected_headers)]
                                data_rows.append(row_data)
                                logging.debug(f"Added row: {row_data}")

            if not data_rows:
                logging.error("No data rows were extracted from the PDF")
                return None

            logging.debug(f"Total rows extracted: {len(data_rows)}")
            logging.debug("Sample of extracted rows:")
            for i, row in enumerate(data_rows[:3]):  # Log first 3 rows
                logging.debug(f"Row {i}: {row}")

            # Create DataFrame
            df = pd.DataFrame(data_rows, columns=expected_headers)
            df = df.drop_duplicates(subset=['VIN'], keep='first')

            # Create temporary file for output
            temp_file = tempfile.NamedTemporaryFile(delete=False)

            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    # Write the data starting from row 5 to leave space for title and summary
                    df.to_excel(writer, index=False, sheet_name='Vehicle Inventory', startrow=5)

                    workbook = writer.book
                    worksheet = writer.sheets['Vehicle Inventory']

                    # Add title and summary information
                    if title:
                        cell = worksheet.cell(row=1, column=1, value=title)
                        cell.font = openpyxl.styles.Font(bold=True, size=12)

                    # Add summary information
                    for idx, info in enumerate(summary_info, start=2):
                        cell = worksheet.cell(row=idx, column=1, value=info)
                        cell.font = openpyxl.styles.Font(size=11)

                    # Merge cells for title and summary
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