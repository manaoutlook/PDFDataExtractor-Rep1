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
        
        Args:
            name: Template identifier (e.g., 'ANZ_Personal')
            patterns: Dictionary of regex patterns for different fields
            layout: Dictionary defining the relative positions of key elements
        """
        self.name = name
        self.patterns = patterns
        self.layout = layout

    def match_score(self, text: str) -> float:
        """
        Calculate how well this template matches the given text
        
        Returns:
            float: Score between 0 and 1, higher means better match
        """
        score = 0
        total_patterns = 0
        
        for field, patterns in self.patterns.items():
            for pattern in patterns:
                total_patterns += 1
                try:
                    if re.search(pattern, text, re.IGNORECASE):
                        score += 1
                except Exception as e:
                    logger.error(f"Error matching pattern {pattern}: {str(e)}")
                    
        return score / total_patterns if total_patterns > 0 else 0

class TemplateManager:
    def __init__(self, templates_dir: str = "templates"):
        """
        Initialize the template manager
        
        Args:
            templates_dir: Directory containing template JSON files
        """
        self.templates: List[BankStatementTemplate] = []
        self.templates_dir = templates_dir
        self._load_templates()

    def _load_templates(self):
        """Load all template definitions from the templates directory"""
        try:
            if not os.path.exists(self.templates_dir):
                os.makedirs(self.templates_dir)
                self._create_default_templates()
                
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
            }
        ]

        for template in default_templates:
            filename = f"{template['name'].lower()}.json"
            filepath = os.path.join(self.templates_dir, filename)
            with open(filepath, 'w') as f:
                json.dump(template, f, indent=2)
            logger.debug(f"Created default template: {filename}")

    def find_matching_template(self, text: str) -> Optional[BankStatementTemplate]:
        """
        Find the best matching template for the given text
        
        Args:
            text: Text content from the bank statement
            
        Returns:
            BankStatementTemplate or None if no good match found
        """
        best_score = 0
        best_template = None
        
        for template in self.templates:
            score = template.match_score(text)
            if score > best_score:
                best_score = score
                best_template = template
                
        # Require at least 50% match to consider it valid
        return best_template if best_score >= 0.5 else None

    def get_template(self, name: str) -> Optional[BankStatementTemplate]:
        """Get a specific template by name"""
        for template in self.templates:
            if template.name.lower() == name.lower():
                return template
        return None

    def add_template(self, template_data: Dict) -> bool:
        """
        Add a new template to the system
        
        Args:
            template_data: Dictionary containing template definition
            
        Returns:
            bool: True if successful, False otherwise
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
