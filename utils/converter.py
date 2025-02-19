import PyPDF2
import pandas as pd
import tempfile
import logging
from typing import Optional

def convert_pdf(pdf_path: str, output_format: str = 'excel') -> Optional[str]:
    """
    Convert PDF to Excel or CSV format with proper header handling

    Args:
        pdf_path (str): Path to the PDF file
        output_format (str): Either 'excel' or 'csv'

    Returns:
        str: Path to the converted file
    """
    try:
        # Read PDF
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)

            # Extract text from all pages
            text_content = []
            for page in pdf_reader.pages:
                text_content.append(page.extract_text())

            # Process the text content
            all_lines = []
            for page_text in text_content:
                lines = [line.strip() for line in page_text.split('\n') if line.strip()]
                all_lines.extend(lines)

            if not all_lines:
                logging.error("No content found in PDF")
                return None

            # First line contains headers
            headers = [header.strip() for header in all_lines[0].split() if header.strip()]

            # Process remaining lines as data
            data_rows = []
            for line in all_lines[1:]:
                # Split by whitespace and create row with same number of columns as headers
                row = [cell.strip() for cell in line.split()]
                # Ensure row has same number of columns as headers
                if len(row) > 0:  # Only add non-empty rows
                    # Pad or truncate row to match header length
                    if len(row) < len(headers):
                        row.extend([''] * (len(headers) - len(row)))
                    elif len(row) > len(headers):
                        row = row[:len(headers)]
                    data_rows.append(row)

            # Create DataFrame with explicit headers
            df = pd.DataFrame(data_rows, columns=headers)

            # Create temporary file for output
            temp_file = tempfile.NamedTemporaryFile(delete=False)

            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                df.to_excel(output_path, index=False)
            else:
                output_path = f"{temp_file.name}.csv"
                df.to_csv(output_path, index=False)

            return output_path

    except Exception as e:
        logging.error(f"Conversion error: {str(e)}")
        return None