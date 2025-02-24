import logging
import requests
from urllib.parse import urlparse
import time
from bs4 import BeautifulSoup
import json
import re

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
            dynamic_imports = []

            # Also search for Adobe-related strings in the entire HTML
            adobe_patterns = [
                r'adobe.*api',
                r'pdf.*services.*api',
                r'dc-view-sdk',
                r'documentcloud',
                r'acrobat.*services'
            ]

            for pattern in adobe_patterns:
                matches = re.findall(pattern, response.text, re.IGNORECASE)
                if matches:
                    adobe_related.extend(matches)

            for script in scripts:
                src = script.get('src', '')
                if src:
                    if 'adobe' in src.lower():
                        adobe_related.append(src)
                    parsed = urlparse(src)
                    if parsed.path.endswith('.js'):
                        api_endpoints.append(src)

                # Check inline scripts
                if script.string:
                    # Look for dynamic imports
                    if 'import(' in script.string:
                        dynamic_imports.extend(re.findall(r'import\([\'"](.+?)[\'"]\)', script.string))

                    # Check for Adobe references
                    if any(re.search(pattern, script.string, re.IGNORECASE) for pattern in adobe_patterns):
                        adobe_related.append('Found Adobe reference in inline script')

                    # Look for API endpoints
                    if 'api' in script.string.lower():
                        api_calls = re.findall(r'[\'"`](/api/[^\'"`]+)[\'"`]', script.string)
                        api_endpoints.extend(api_calls)

            return {
                'adobe_related': list(set(adobe_related)),
                'api_endpoints': list(set(api_endpoints)),
                'dynamic_imports': list(set(dynamic_imports)),
                'status_code': response.status_code,
                'headers': dict(response.headers)
            }

        except Exception as e:
            logger.error(f"Error analyzing initial page: {str(e)}")
            return None

    def analyze_file_upload(self, file_path):
        """Analyze the file upload process"""
        try:
            logger.info(f"Analyzing file upload process")

            # First check the page source for upload-related information
            response = self.session.get(self.base_url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for upload-related elements
            upload_info = {
                'form_endpoints': [],
                'api_endpoints': [],
                'adobe_endpoints': [],
                'headers': {},
                'upload_handlers': []
            }

            # Check for form actions
            forms = soup.find_all('form')
            for form in forms:
                if form.get('action'):
                    upload_info['form_endpoints'].append(form['action'])

            # Look for JavaScript handlers
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    # Look for upload handlers
                    if 'upload' in script.string.lower():
                        handlers = re.findall(r'(?:fetch|axios\.post)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]', script.string)
                        upload_info['upload_handlers'].extend(handlers)

                    # Look for Adobe-related upload endpoints
                    adobe_endpoints = re.findall(r'https?://[^\'"`]*adobe[^\'"`]+', script.string)
                    if adobe_endpoints:
                        upload_info['adobe_endpoints'].extend(adobe_endpoints)

            # Check common API endpoints
            common_endpoints = [
                '/api/upload',
                '/api/file/upload',
                '/upload',
                '/api/convert/upload'
            ]

            for endpoint in common_endpoints:
                try:
                    response = self.session.options(f"{self.base_url}{endpoint}")
                    if response.status_code != 404:
                        upload_info['api_endpoints'].append({
                            'endpoint': endpoint,
                            'methods': response.headers.get('Allow', '').split(','),
                            'cors': response.headers.get('Access-Control-Allow-Origin', '')
                        })
                except:
                    continue

            return upload_info

        except Exception as e:
            logger.error(f"Error analyzing file upload: {str(e)}")
            return None

    def analyze_conversion_process(self):
        """Analyze the conversion process and endpoints"""
        try:
            logger.info("Analyzing conversion process")

            conversion_info = {
                'endpoints': [],
                'adobe_services': [],
                'headers': [],
                'features': []
            }

            # Check for conversion-related endpoints
            response = self.session.get(self.base_url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for conversion features
            for script in soup.find_all('script'):
                if script.string:
                    # Look for Adobe PDF Services features
                    if re.search(r'PDFServicesSDK|createPDFOperation|extractPDFOperation', script.string):
                        conversion_info['adobe_services'].append('Adobe PDF Services SDK detected')

                    # Look for conversion endpoints
                    endpoints = re.findall(r'[\'"`](/(?:api/)?(?:convert|process|extract)/[^\'"`]+)[\'"`]', script.string)
                    conversion_info['endpoints'].extend(endpoints)

                    # Look for feature descriptions
                    features = re.findall(r'(?:converts?|extracts?|process(?:es)?|OCR)\s+(?:PDF|bank\s+statements?|documents?)', script.string, re.IGNORECASE)
                    conversion_info['features'].extend(features)

            # Check response headers for Adobe-related information
            conversion_info['headers'] = dict(response.headers)

            return conversion_info

        except Exception as e:
            logger.error(f"Error analyzing conversion process: {str(e)}")
            return None

    # Add client-side analysis capabilities
    def analyze_client_scripts(self):
        """Analyze client-side JavaScript for PDF processing clues"""
        try:
            logger.info("Analyzing client-side JavaScript")
            response = self.session.get(self.base_url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find all script URLs
            script_urls = []
            for script in soup.find_all('script', src=True):
                if script['src'].startswith('/_next/static/chunks/'):
                    script_urls.append(script['src'])

            # Download and analyze each script
            pdf_processing_info = {
                'possible_services': [],
                'api_endpoints': [],
                'libraries': [],
                'features': []
            }

            for url in script_urls:
                try:
                    script_url = f"{self.base_url}{url}"
                    script_response = self.session.get(script_url)
                    script_content = script_response.text.lower()

                    # Look for PDF processing libraries
                    pdf_libraries = [
                        'pdf-lib',
                        'pdfjs',
                        'adobe',
                        'documentservices',
                        'acrobat',
                        'pdfservices'
                    ]

                    for lib in pdf_libraries:
                        if lib in script_content:
                            pdf_processing_info['libraries'].append(lib)

                    # Look for API endpoints
                    api_patterns = [
                        r'(?:https?:)?//[^"\']+(?:adobe|acrobat)[^"\']+',
                        r'/api/[^"\']+(?:pdf|convert|process)[^"\']*'
                    ]

                    for pattern in api_patterns:
                        matches = re.findall(pattern, script_content)
                        pdf_processing_info['api_endpoints'].extend(matches)

                    # Look for PDF processing features
                    feature_patterns = [
                        r'(?:extract|parse|convert|process)(?:\s+|_)(?:pdf|document|statement)',
                        r'ocr[\s_](?:process|extract|scan)',
                        r'document[\s_](?:ai|intelligence|processing)'
                    ]

                    for pattern in feature_patterns:
                        matches = re.findall(pattern, script_content)
                        pdf_processing_info['features'].extend(matches)

                except Exception as e:
                    logger.error(f"Error analyzing script {url}: {str(e)}")
                    continue

            return pdf_processing_info

        except Exception as e:
            logger.error(f"Error in client script analysis: {str(e)}")
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

    # Add client-side script analysis
    logger.info("\nStarting client-side script analysis")
    client_analysis = analyzer.analyze_client_scripts()
    print("\nClient-Side Script Analysis:")
    print(json.dumps(client_analysis, indent=2))

if __name__ == "__main__":
    main()