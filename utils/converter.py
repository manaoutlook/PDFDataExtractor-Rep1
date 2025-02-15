import PyPDF2
import pandas as pd
import tempfile
import logging
from typing import Optional

def convert_pdf(pdf_path: str, output_format: str = 'excel') -> Optional[str]:
    """
    Convert PDF to Excel or CSV format
    
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
            
            # Process the text content into rows
            rows = []
            for page_text in text_content:
                lines = page_text.split('\n')
                for line in lines:
                    if line.strip():
                        # Split line by whitespace and create row
                        row = [cell.strip() for cell in line.split()]
                        rows.append(row)
            
            # Create DataFrame
            df = pd.DataFrame(rows)
            
            # Create temporary file for output
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            
            if output_format == 'excel':
                output_path = f"{temp_file.name}.xlsx"
                df.to_excel(output_path, index=False, header=False)
            else:
                output_path = f"{temp_file.name}.csv"
                df.to_csv(output_path, index=False, header=False)
            
            return output_path
            
    except Exception as e:
        logging.error(f"Conversion error: {str(e)}")
        return None
