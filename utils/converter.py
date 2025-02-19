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
        # Read PDF
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            
            # Extract text from all pages
            all_text = []
            for page in pdf_reader.pages:
                text = page.extract_text()
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                all_text.extend(lines)
            
            # Try to identify table structure
            data_rows = []
            headers = None
            
            for line in all_text:
                # Skip empty lines
                if not line:
                    continue
                    
                # Split the line into columns
                columns = line.split()
                
                # If headers aren't set, use the first non-empty row
                if not headers and len(columns) > 1:
                    headers = columns
                    continue
                    
                # Process data rows
                if headers and len(columns) > 0:
                    # Try to maintain the same number of columns as headers
                    row_data = []
                    current_col = ""
                    
                    for word in columns:
                        if len(row_data) < len(headers) - 1:
                            row_data.append(word)
                        else:
                            current_col += " " + word if current_col else word
                            
                    if current_col:
                        row_data.append(current_col)
                        
                    # Only add rows that have data
                    if len(row_data) > 0:
                        # Pad with empty strings if needed
                        while len(row_data) < len(headers):
                            row_data.append('')
                        data_rows.append(row_data[:len(headers)])

            # Create DataFrame
            df = pd.DataFrame(data_rows, columns=headers if headers else range(len(data_rows[0])))

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