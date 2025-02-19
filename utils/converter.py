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
                    if 'VIN' in line and any(header in line for header in expected_headers):
                        continue

                    # Process data row - look for VIN-like pattern
                    vin_patterns = [
                        r'^([A-Z0-9]{17})',  # Standard 17-char VIN
                        r'^([A-Z0-9]{6,}(?=\s))',  # Shorter VIN-like identifier
                        r'^((?:New\s)?[A-Z0-9]{1,5}\s?[A-Z0-9]{1,12}(?=\s))'  # Special cases like "New V"
                    ]

                    for pattern in vin_patterns:
                        vin_match = re.match(pattern, line)
                        if vin_match:
                            # Get the VIN and remaining data
                            vin = vin_match.group(1).strip()
                            remaining = line[vin_match.end():].strip()

                            # Split remaining data by multiple spaces
                            parts = [p.strip() for p in re.split(r'\s{2,}', remaining)]
                            parts = [p for p in parts if p.strip()]

                            # Combine VIN with remaining data
                            row_data = [vin] + parts

                            # Clean and validate row data
                            if len(row_data) >= 3:  # Must have at least VIN, Make, Model
                                # Pad with empty strings if needed
                                while len(row_data) < len(expected_headers):
                                    row_data.append('')

                                # Trim if too long
                                row_data = row_data[:len(expected_headers)]
                                data_rows.append(row_data)
                                logging.debug(f"Added row: {row_data}")
                            break  # Stop checking patterns if we found a match

            if not data_rows:
                logging.error("No data rows were extracted from the PDF")
                return None

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

                    # Add title and summary information
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