import logging
import re
from typing import Dict, List, Optional, Tuple
import json
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class BankStatementTemplate:
    def __init__(self, name: str, patterns: Dict[str, List[str]], layout: Dict[str, Tuple[float, float, float, float]]):
        """
        Initialize a bank statement template
        """
        self.name = name
        self.patterns = patterns
        self.layout = layout

    def match_score(self, text: str) -> float:
        """
        Calculate how well this template matches the given text
        """
        score = 0
        total_patterns = 0
        matches_found = []

        for field, patterns in self.patterns.items():
            for pattern in patterns:
                total_patterns += 1
                try:
                    if re.search(pattern, text, re.IGNORECASE):
                        score += 1
                        matches_found.append(f"Matched {field} pattern: {pattern}")
                    else:
                        logging.debug(f"No match for {field} pattern: {pattern}")
                except Exception as e:
                    logger.error(f"Error matching pattern {pattern}: {str(e)}")

        final_score = score / total_patterns if total_patterns > 0 else 0
        logging.debug(f"Template {self.name} score: {final_score}")
        if matches_found:
            logging.debug(f"Matches found for {self.name}: {', '.join(matches_found)}")
        return final_score

class TemplateManager:
    def __init__(self, templates_dir: str = "templates"):
        """
        Initialize the template manager
        """
        self.templates: List[BankStatementTemplate] = []
        self.templates_dir = templates_dir
        self._load_templates()

    def _create_default_templates(self):
        """Create default templates for common bank statements"""
        default_templates = [
            {
                "name": "ANZ_Personal",
                "patterns": {
                    "header": [
                        r"ANZ\s+Bank",
                        r"Statement\s+Period",
                        r"Account\s+Summary"
                    ],
                    "transaction": [
                        r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
                        r"Opening\s+Balance",
                        r"Closing\s+Balance"
                    ],
                    "footer": [
                        r"End\s+of\s+Statement",
                        r"Page\s+\d+\s+of\s+\d+"
                    ]
                },
                "layout": {
                    "date": (0, 0.15, 0, 0.1),
                    "description": (0.15, 0.6, 0, 0.1),
                    "amount": (0.6, 0.8, 0, 0.1),
                    "balance": (0.8, 1.0, 0, 0.1)
                }
            },
            {
                "name": "RBS_Personal",
                "patterns": {
                    "header": [
                        r"Royal\s+Bank\s+of\s+Scotland",
                        r"RBS",
                        r"Statement\s+of\s+Account",
                        r"Account\s+Details",
                        r"Your\s+Account\s+Summary"
                    ],
                    "transaction": [
                        r"\d{1,2}(?:st|nd|rd|th)?\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*",
                        r"(?:PAYMENT|TFR|DD|DR|CR|ATM|POS|BGC|DEB|SO)",
                        r"(?:WITHDRAWAL|DEPOSIT|TRANSFER|STANDING ORDER|DIRECT DEBIT)",
                        r"\d{2}[-/]\d{2}[-/]\d{2,4}"
                    ],
                    "footer": [
                        r"Balance\s+(?:brought|carried)\s+forward",
                        r"Page\s+\d+\s+of\s+\d+",
                        r"Statement\s+period",
                        r"Opening\s+balance",
                        r"Closing\s+balance"
                    ]
                },
                "layout": {
                    "date": (0, 0.15, 0, 0.1),
                    "description": (0.15, 0.6, 0, 0.1),
                    "withdrawals": (0.6, 0.75, 0, 0.1),
                    "deposits": (0.75, 0.9, 0, 0.1),
                    "balance": (0.9, 1.0, 0, 0.1)
                }
            }
        ]

        for template in default_templates:
            filename = f"{template['name'].lower()}.json"
            filepath = os.path.join(self.templates_dir, filename)
            with open(filepath, 'w') as f:
                json.dump(template, f, indent=2)
            logger.debug(f"Created default template: {filename}")

        self._load_templates()

    def _load_templates(self):
        """Load all template definitions from the templates directory"""
        try:
            if not os.path.exists(self.templates_dir):
                os.makedirs(self.templates_dir)
                self._create_default_templates()

            self.templates = []  # Reset templates list before loading
            for filename in os.listdir(self.templates_dir):
                if filename.endswith('.json'):
                    try:
                        with open(os.path.join(self.templates_dir, filename)) as f:
                            template_data = json.load(f)
                            template = BankStatementTemplate(
                                name=template_data['name'],
                                patterns=template_data['patterns'],
                                layout=template_data['layout']
                            )
                            self.templates.append(template)
                            logger.debug(f"Loaded template: {template.name}")
                    except Exception as e:
                        logger.error(f"Error loading template {filename}: {str(e)}")

        except Exception as e:
            logger.error(f"Error loading templates: {str(e)}")

    def find_matching_template(self, text: str) -> Optional[BankStatementTemplate]:
        """
        Find the best matching template for the given text
        """
        best_score = 0
        best_template = None

        logging.debug("Starting template matching process")
        logging.debug(f"Text sample: {text[:200]}...")  # Log first 200 chars of text

        for template in self.templates:
            logging.debug(f"Checking template: {template.name}")
            score = template.match_score(text)
            logging.debug(f"Template {template.name} scored: {score}")
            if score > best_score:
                best_score = score
                best_template = template
                logging.debug(f"New best template: {template.name} with score {score}")

        # Require at least 30% match to consider it valid (lowered threshold for testing)
        if best_score >= 0.3:
            logging.info(f"Selected template {best_template.name} with score {best_score}")
            return best_template
        else:
            logging.warning(f"No template matched well enough. Best score was {best_score}")
            return None

    def get_template(self, name: str) -> Optional[BankStatementTemplate]:
        """Get a specific template by name"""
        for template in self.templates:
            if template.name.lower() == name.lower():
                return template
        return None

    def add_template(self, template_data: Dict) -> bool:
        """
        Add a new template to the system
        """
        try:
            template = BankStatementTemplate(
                name=template_data['name'],
                patterns=template_data['patterns'],
                layout=template_data['layout']
            )

            # Save to file
            filename = f"{template.name.lower()}.json"
            filepath = os.path.join(self.templates_dir, filename)
            with open(filepath, 'w') as f:
                json.dump(template_data, f, indent=2)

            self.templates.append(template)
            logger.debug(f"Added new template: {template.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding template: {str(e)}")
            return False