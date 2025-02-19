import PyPDF2
import pandas as pd
import tempfile
import logging
from typing import Optional
import openpyxl

def convert_pdf(pdf_path: str, output_format: str = 'excel') -> Optional[str]:
    """
    Convert PDF to Excel or CSV format with proper header handling for vehicle inventory data

    Args:
        pdf_path (str): Path to the PDF file
        output_format (str): Either 'excel' or 'csv'

    Returns:
        str: Path to the converted file
    """
    try:
        # Define expected headers
        expected_headers = [
            'VIN', 'Make', 'Model', 'Year', 'Status', 'Location',
            'Test', 'Location', 'Drive', 'Type'
        ]

        # Read PDF
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)

            # Extract text from all pages
            text_content = []
            for page in pdf_reader.pages:
                text = page.extract_text()
                text_content.append(text)

            # Process the text content
            data_dict = {header: [] for header in expected_headers}
            current_header = None

            for page_text in text_content:
                lines = [line.strip() for line in page_text.split('\n') if line.strip()]

                for line in lines:
                    # Check if this line is a header
                    if line in expected_headers:
                        current_header = line
                        continue

                    # If we have a current header and the line isn't another header
                    if current_header and line not in expected_headers:
                        data_dict[current_header].append(line)

            # Create DataFrame with the collected data
            max_length = max(len(values) for values in data_dict.values())
            for header in data_dict:
                # Pad shorter columns with empty strings
                data_dict[header].extend([''] * (max_length - len(data_dict[header])))

            df = pd.DataFrame(data_dict)

            # Create temporary file for output
            temp_file = tempfile.NamedTemporaryFile(delete=False)

            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Vehicle Inventory')
                    # Get the workbook and the worksheet
                    workbook = writer.book
                    worksheet = writer.sheets['Vehicle Inventory']

                    # Format the header row
                    for col in range(len(df.columns)):
                        cell = worksheet.cell(row=1, column=col + 1)
                        cell.fill = openpyxl.styles.PatternFill(start_color="FFFF00", 
                                                              end_color="FFFF00",
                                                              fill_type="solid")
            else:
                output_path = f"{temp_file.name}.csv"
                df.to_csv(output_path, index=False)

            return output_path

    except Exception as e:
        logging.error(f"Conversion error: {str(e)}")
        return None