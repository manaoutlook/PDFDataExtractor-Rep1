import PyPDF2
import pandas as pd
import tempfile
import logging
from typing import Optional
import openpyxl

def convert_pdf(pdf_path: str, output_format: str = 'excel') -> Optional[str]:
    """
    Convert PDF to Excel or CSV format with proper table structure preservation

    Args:
        pdf_path (str): Path to the PDF file
        output_format (str): Either 'excel' or 'csv'

    Returns:
        str: Path to the converted file
    """
    try:
        # Define expected headers
        expected_headers = [
            'VIN', 'Make', 'Model', 'Year', 'Status', 'Location', 'Make Code', 'Drive Type'
        ]

        # Read PDF
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)

            # Extract text from all pages
            data_rows = []
            header_found = False

            for page in pdf_reader.pages:
                text = page.extract_text()
                lines = [line.strip() for line in text.split('\n') if line.strip()]

                for line in lines:
                    # Skip summary lines
                    if any(x in line for x in ['Total Vehicles:', 'Active Vehicles:', 'Vehicles in Maintenance:']):
                        continue

                    # Skip empty lines
                    if not line:
                        continue

                    # Process the line
                    if not header_found and 'VIN' in line and 'Make' in line and 'Model' in line:
                        header_found = True
                        continue

                    if header_found:
                        # Split the line into parts
                        parts = line.split()
                        if len(parts) >= 3:  # Ensure we have at least VIN, Make, and Model
                            current_row = []
                            current_field = ''

                            for word in parts:
                                # If we find something that looks like a VIN (alphanumeric, length > 10)
                                if len(word) > 10 and any(c.isalpha() for c in word) and any(c.isdigit() for c in word):
                                    if current_field:
                                        current_row.append(current_field.strip())
                                        current_field = ''
                                    current_row.append(word)
                                else:
                                    if current_field:
                                        current_field += ' ' + word
                                    else:
                                        current_field = word

                            # Add the last field if any
                            if current_field:
                                current_row.append(current_field.strip())

                            # Only add rows that look valid (have enough data)
                            if len(current_row) >= 3 and len(current_row[0]) > 10:  # VIN is typically > 10 chars
                                # Ensure we have exactly the right number of columns
                                while len(current_row) < len(expected_headers):
                                    current_row.append('')
                                data_rows.append(current_row[:len(expected_headers)])

            # Create DataFrame
            df = pd.DataFrame(data_rows, columns=expected_headers)

            # Create temporary file for output
            temp_file = tempfile.NamedTemporaryFile(delete=False)

            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Vehicle Inventory')

                    # Format the header row
                    workbook = writer.book
                    worksheet = writer.sheets['Vehicle Inventory']

                    # Yellow background for header row
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

            return output_path

    except Exception as e:
        logging.error(f"Conversion error: {str(e)}")
        return None