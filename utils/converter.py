import PyPDF2
import pandas as pd
import tempfile
import logging
from typing import Optional
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
import re

def convert_pdf(pdf_path: str, output_format: str = 'excel') -> Optional[str]:
    try:
        expected_headers = [
            'VIN', 'Make', 'Model', 'Year', 'Status', 'Location', 'Make Code', 'Drive Type'
        ]

        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            data_rows = []
            title = None
            summary_info = []

            logging.debug(f"Processing PDF with {len(pdf_reader.pages)} pages")

            for page in pdf_reader.pages:
                text = page.extract_text()
                lines = [line.strip() for line in text.split('\n') if line.strip()]

                for line in lines:
                    logging.debug(f"Processing line: {line}")

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

                    # Skip the header row itself
                    if all(header in line for header in ['VIN', 'Make', 'Model']):
                        logging.debug("Skipping header row")
                        continue

                    # Process data rows - using multiple patterns to match different VIN formats
                    patterns = [
                        r'^(5TFU[A-Z0-9]{13})',  # Toyota pattern
                        r'^(WVWA[A-Z0-9]{12})',  # VW pattern
                        r'^(1HGC[A-Z0-9]{13})',  # Honda pattern
                        r'^(New\s*V)',           # Special case for "New V"
                        r'^(D11\s*Car)',         # Special case for "D11 Car"
                        r'^([A-Za-z0-9]{1,8})',  # Generic pattern for other cases
                    ]

                    matched = False
                    for pattern in patterns:
                        match = re.match(pattern, line)
                        if match:
                            vin = match.group(1).strip()
                            remaining = line[match.end():].strip()

                            # Split remaining data by multiple spaces or tabs
                            parts = [p for p in re.split(r'\s{2,}|\t+', remaining) if p.strip()]

                            # Combine VIN with remaining data
                            row_data = [vin] + parts

                            # Clean row data
                            row_data = [col.strip() for col in row_data if col.strip()]

                            # Must have at least VIN, Make, Model
                            if len(row_data) >= 3:
                                # Pad missing columns with empty strings
                                while len(row_data) < len(expected_headers):
                                    row_data.append('')

                                # Trim excess columns
                                row_data = row_data[:len(expected_headers)]

                                logging.debug(f"Extracted row: {row_data}")
                                data_rows.append(row_data)
                                matched = True
                                break

                    if not matched:
                        logging.debug(f"No match found for line: {line}")

            if not data_rows:
                logging.error("No data rows were extracted from the PDF")
                return None

            logging.debug(f"Total rows extracted: {len(data_rows)}")

            # Create DataFrame
            df = pd.DataFrame(data_rows, columns=expected_headers)
            df = df.drop_duplicates(subset=['VIN'], keep='first')

            # Create temporary file for output
            temp_file = tempfile.NamedTemporaryFile(delete=False)

            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    # Write the data starting from row 5 to leave space for title and summary
                    df.to_excel(writer, index=False, sheet_name='Vehicle Inventory', startrow=4)

                    workbook = writer.book
                    worksheet = writer.sheets['Vehicle Inventory']

                    # Add title
                    if title:
                        title_cell = worksheet.cell(row=1, column=1, value=title)
                        title_cell.font = Font(bold=True, size=14)
                        worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(expected_headers))
                        title_cell.alignment = Alignment(horizontal='center')

                    # Add summary information
                    for idx, info in enumerate(summary_info, start=2):
                        info_cell = worksheet.cell(row=idx, column=1, value=info)
                        info_cell.font = Font(size=11)
                        worksheet.merge_cells(start_row=idx, start_column=1, end_row=idx, end_column=len(expected_headers))
                        info_cell.alignment = Alignment(horizontal='left')

                    # Style the header row (row 5 due to title and summary)
                    header_row = 5
                    header_fill = PatternFill(start_color='1F4E78', end_color='1F4E78', fill_type='solid')
                    header_font = Font(color='FFFFFF', bold=True)
                    thin_border = Border(
                        left=Side(style='thin'),
                        right=Side(style='thin'),
                        top=Side(style='thin'),
                        bottom=Side(style='thin')
                    )

                    for col, header in enumerate(expected_headers, start=1):
                        cell = worksheet.cell(row=header_row, column=col)
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.alignment = Alignment(horizontal='center')
                        cell.border = thin_border

                    # Style data rows and adjust column widths
                    for col in worksheet.columns:
                        max_length = 0
                        col_letter = col[0].column_letter

                        for cell in col:
                            try:
                                cell.alignment = Alignment(horizontal='center')
                                cell.border = thin_border
                                if len(str(cell.value)) > max_length:
                                    max_length = len(str(cell.value))
                            except:
                                pass

                        adjusted_width = (max_length + 2) * 1.2
                        worksheet.column_dimensions[col_letter].width = adjusted_width

            else:
                output_path = f"{temp_file.name}.csv"
                df.to_csv(output_path, index=False)

            return output_path

    except Exception as e:
        logging.error(f"Conversion error: {str(e)}")
        return None