import logging
import requests
from urllib.parse import urlparse
import time
from bs4 import BeautifulSoup
import json

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class PDFServiceAnalyzer:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://bankstatementconverter.com"
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def analyze_initial_page(self):
        """Analyze the initial page load and scripts"""
        try:
            logger.info("Analyzing initial page load")
            response = self.session.get(self.base_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for Adobe-related scripts and endpoints
            scripts = soup.find_all('script')
            adobe_related = []
            api_endpoints = []
            
            for script in scripts:
                src = script.get('src', '')
                if src:
                    if 'adobe' in src.lower():
                        adobe_related.append(src)
                    parsed = urlparse(src)
                    if parsed.path.endswith('.js'):
                        api_endpoints.append(src)
                
                # Check inline scripts for Adobe references
                if script.string:
                    if 'adobe' in script.string.lower():
                        adobe_related.append('Inline script with Adobe reference')
                    
                    # Look for API endpoints
                    if 'api' in script.string.lower():
                        api_endpoints.append('Found API reference in inline script')

            return {
                'adobe_related': adobe_related,
                'api_endpoints': api_endpoints,
                'status_code': response.status_code,
                'headers': dict(response.headers)
            }

        except Exception as e:
            logger.error(f"Error analyzing initial page: {str(e)}")
            return None

    def analyze_file_upload(self, file_path):
        """Analyze the file upload process"""
        try:
            logger.info(f"Analyzing file upload process for: {file_path}")
            
            # First get the upload endpoint
            response = self.session.get(f"{self.base_url}/api/upload")
            if response.status_code == 404:
                logger.info("Direct upload endpoint not found, looking for alternatives")
                
            # Try to find the actual upload endpoint from the page source
            main_page = self.session.get(self.base_url)
            soup = BeautifulSoup(main_page.text, 'html.parser')
            
            # Look for form action or API endpoints
            forms = soup.find_all('form')
            upload_endpoints = []
            for form in forms:
                if form.get('action'):
                    upload_endpoints.append(form['action'])
                    
            # Look for fetch/axios calls in scripts
            scripts = soup.find_all('script')
            api_calls = []
            for script in scripts:
                if script.string and 'fetch(' in script.string:
                    api_calls.append('Found fetch API call')
                if script.string and 'axios' in script.string:
                    api_calls.append('Found axios API call')

            return {
                'upload_endpoints': upload_endpoints,
                'api_calls': api_calls
            }

        except Exception as e:
            logger.error(f"Error analyzing file upload: {str(e)}")
            return None

    def analyze_conversion_process(self):
        """Analyze the conversion process and endpoints"""
        try:
            logger.info("Analyzing conversion process")
            
            # Look for conversion-related endpoints
            endpoints_to_check = [
                '/api/convert',
                '/api/process',
                '/convert',
                '/process'
            ]
            
            conversion_endpoints = []
            for endpoint in endpoints_to_check:
                response = self.session.get(f"{self.base_url}{endpoint}")
                if response.status_code != 404:
                    conversion_endpoints.append({
                        'endpoint': endpoint,
                        'status': response.status_code,
                        'headers': dict(response.headers)
                    })
                    
            return {
                'conversion_endpoints': conversion_endpoints
            }

        except Exception as e:
            logger.error(f"Error analyzing conversion process: {str(e)}")
            return None

def main():
    analyzer = PDFServiceAnalyzer()
    
    # Analyze initial page load
    logger.info("Starting initial page analysis")
    initial_analysis = analyzer.analyze_initial_page()
    print("\nInitial Page Analysis:")
    print(json.dumps(initial_analysis, indent=2))
    
    # Analyze file upload process
    logger.info("\nStarting file upload analysis")
    upload_analysis = analyzer.analyze_file_upload("test.pdf")
    print("\nFile Upload Analysis:")
    print(json.dumps(upload_analysis, indent=2))
    
    # Analyze conversion process
    logger.info("\nStarting conversion process analysis")
    conversion_analysis = analyzer.analyze_conversion_process()
    print("\nConversion Process Analysis:")
    print(json.dumps(conversion_analysis, indent=2))

if __name__ == "__main__":
    main()
