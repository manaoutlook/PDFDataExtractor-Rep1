import logging
import re
from typing import Dict, List, Optional, Tuple
import json
from extensions import db
from models import BankTemplate, TemplateSimilarity

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
                        logger.debug(f"No match for {field} pattern: {pattern}")
                except Exception as e:
                    logger.error(f"Error matching pattern {pattern}: {str(e)}")

        final_score = score / total_patterns if total_patterns > 0 else 0
        logger.debug(f"Template {self.name} score: {final_score}")
        if matches_found:
            logger.debug(f"Matches found for {self.name}: {', '.join(matches_found)}")
        return final_score

class TemplateManager:
    def __init__(self):
        """
        Initialize the template manager with database support
        """
        self.templates: List[BankStatementTemplate] = []
        self._load_templates()

    def _create_default_templates(self):
        """Create default templates for common bank statements"""
        default_templates = [
            {
                "name": "RBS_Personal",
                "description": "Royal Bank of Scotland Personal Account Statement",
                "patterns": {
                    "header": [
                        r"Royal\s+Bank\s+of\s+Scotland",
                        r"RBS",
                        r"Statement\s+of\s+Account",
                        r"Account\s+Details",
                        r"Your\s+Account\s+Summary"
                    ],
                    "transaction": [
                        # Date formats
                        r"\d{1,2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",  # 26 APR
                        r"\d{1,2}[A-Z]{3}\d{2}",  # 26APR23
                        r"\d{2}[-/]\d{2}[-/]\d{2,4}",  # DD/MM/YYYY
                        # Transaction codes and types
                        r"(?:PAYMENT|TFR|DD|DR|CR|ATM|POS|BGC|DEB|SO)",
                        r"(?:WITHDRAWAL|DEPOSIT|TRANSFER|STANDING ORDER|DIRECT DEBIT)"
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
            },
            {
                "name": "ANZ_Personal",
                "description": "ANZ Bank Personal Account Statement",
                "patterns": {
                    "header": [
                        r"ANZ\s+Bank",
                        r"Australia\s+and\s+New\s+Zealand\s+Banking",
                        r"Statement\s+Period",
                        r"Account\s+Summary",
                        r"Opening\s+Balance"
                    ],
                    "transaction": [
                        # Date formats
                        r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
                        r"\d{2}/\d{2}/\d{4}",
                        r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}",
                        # Transaction types
                        r"(?:PAYMENT|DEPOSIT|WITHDRAWAL|ATM|EFTPOS|DIRECT CREDIT|DIRECT DEBIT|TRANSFER)",
                        r"(?:Opening Balance|Closing Balance|Balance Brought Forward)"
                    ],
                    "footer": [
                        r"End\s+of\s+Statement",
                        r"Page\s+\d+\s+of\s+\d+",
                        r"Closing\s+Balance",
                        r"For\s+further\s+information"
                    ]
                },
                "layout": {
                    "date": (0, 0.2, 0, 0.1),
                    "description": (0.2, 0.6, 0, 0.1),
                    "amount": (0.6, 0.8, 0, 0.1),
                    "balance": (0.8, 1.0, 0, 0.1)
                }
            }
        ]

        for template_data in default_templates:
            template = BankTemplate.query.filter_by(name=template_data['name']).first()
            if not template:
                template = BankTemplate(
                    name=template_data['name'],
                    description=template_data['description'],
                    patterns=json.dumps(template_data['patterns']),
                    layout=json.dumps(template_data['layout'])
                )
                db.session.add(template)
                logger.debug(f"Created default template: {template.name}")

        try:
            db.session.commit()
            logger.info("Default templates created successfully")
        except Exception as e:
            logger.error(f"Error creating default templates: {str(e)}")
            db.session.rollback()

    def _load_templates(self):
        """Load all templates from database"""
        try:
            # Ensure default templates exist
            if BankTemplate.query.count() == 0:
                logger.info("No templates found in database, creating defaults...")
                self._create_default_templates()

            # Load all templates
            self.templates = []
            for db_template in BankTemplate.query.all():
                template = BankStatementTemplate(
                    name=db_template.name,
                    patterns=json.loads(db_template.patterns),
                    layout=json.loads(db_template.layout)
                )
                self.templates.append(template)
                logger.info(f"Loaded template: {template.name}")

            logger.info(f"Successfully loaded {len(self.templates)} templates")

        except Exception as e:
            logger.error(f"Error loading templates: {str(e)}")

    def find_matching_template(self, text: str) -> Optional[BankStatementTemplate]:
        """
        Find the best matching template for the given text and store similarity scores
        """
        best_score = 0
        best_template = None

        logger.info("Starting template matching process")
        logger.debug(f"Text sample: {text[:200]}...")  # Log first 200 chars of text

        # Get all templates from database
        db_templates = BankTemplate.query.all()

        for template in self.templates:
            logger.info(f"Checking template: {template.name}")
            score = template.match_score(text)
            logger.info(f"Template {template.name} scored: {score}")

            if score > best_score:
                best_score = score
                best_template = template
                logger.info(f"New best template: {template.name} with score {score}")

        # Log the final decision
        if best_template and best_score >= 0.3:
            logger.info(f"Selected template {best_template.name} with score {best_score}")
            logger.debug(f"Selected template patterns: {best_template.patterns}")
            logger.debug(f"Selected template layout: {best_template.layout}")
            return best_template
        else:
            logger.warning(f"No template matched well enough. Best score was {best_score}")
            return None

    def get_template(self, name: str) -> Optional[BankStatementTemplate]:
        """Get a specific template by name"""
        for template in self.templates:
            if template.name.lower() == name.lower():
                return template
        return None