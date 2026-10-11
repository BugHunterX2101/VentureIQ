import re
import logging
from typing import Dict, Any, List, Tuple
from datetime import datetime
import dateparser

logger = logging.getLogger(__name__)

class FieldExtractor:
    """Extract structured fields from raw OCR text using Regex and heuristics"""

    def __init__(self, confidence_threshold: float = 0.6):
        self.confidence_threshold = confidence_threshold
        
        # Regex Patterns
        self.patterns = {
            'amount': [
                r'Total\s+Amount\s*[:\-\s]*[₹$€]?\s*([\d,]+\.?\d{0,2})',
                r'Amount\s+Payable\s*[:\-\s]*[₹$€]?\s*([\d,]+\.?\d{0,2})',
                r'Net\s+Payable\s*[:\-\s]*[₹$€]?\s*([\d,]+\.?\d{0,2})',
                r'Bill\s+Amount\s*[:\-\s]*[₹$€]?\s*([\d,]+\.?\d{0,2})',
                r'[₹$€]\s*([\d,]+\.?\d{0,2})'
            ],
            'bill_number': [
                r'Bill\s+No\.?\s*[:\-\s]*([A-Za-z0-9\-]+)',
                r'Invoice\s+No\.?\s*[:\-\s]*([A-Za-z0-9\-]+)',
                r'Bill\s+Number\s*[:\-\s]*([A-Za-z0-9\-]+)'
            ],
            'consumer_number': [
                r'Consumer\s+No\.?\s*[:\-\s]*([A-Za-z0-9\-]+)',
                r'Account\s+No\.?\s*[:\-\s]*([A-Za-z0-9\-]+)',
                r'Consumer\s+ID\s*[:\-\s]*([A-Za-z0-9\-]+)',
                r'CA\s+No\.?\s*[:\-\s]*([A-Za-z0-9\-]+)'
            ],
            'billing_date': [
                r'Bill\s+Date\s*[:\-\s]*([\d\/\-\.]+)',
                r'Invoice\s+Date\s*[:\-\s]*([\d\/\-\.]+)',
                r'Date\s*[:\-\s]*([\d\/\-\.]+)'
            ],
            'due_date': [
                r'Due\s+Date\s*[:\-\s]*([\d\/\-\.]+)',
                r'Pay\s+By\s*[:\-\s]*([\d\/\-\.]+)'
            ],
            'units_consumed': [
                r'Units\s+Consumed\s*[:\-\s]*([\d\.]+)',
                r'Total\s+Units\s*[:\-\s]*([\d\.]+)',
                r'Consumption\s*[:\-\s]*([\d\.]+)'
            ]
        }

    def extract_fields(self, text: str) -> Dict[str, Any]:
        """Extract all fields from text"""
        logger.info("Extracting fields from text")
        
        fields = {
            'raw_text': text[:500]  # First 500 chars
        }

        # Extract each field
        fields['amount'] = self._extract_amount(text)
        fields['bill_number'] = self._extract_generic(text, 'bill_number')
        fields['consumer_number'] = self._extract_generic(text, 'consumer_number')
        fields['billing_date'] = self._extract_date(text, 'billing_date')
        fields['due_date'] = self._extract_date(text, 'due_date')
        fields['units_consumed'] = self._extract_numeric(text, 'units_consumed')
        
        # Infer Category and Biller (Mock logic for now, or simple keyword search)
        fields['biller_info'] = self._extract_biller_info(text)

        return fields

    def _extract_amount(self, text: str) -> Dict[str, Any]:
        """Extract amount with highest confidence"""
        for pattern in self.patterns['amount']:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                val_str = match.group(1).replace(',', '')
                try:
                    val = float(val_str)
                    return {'value': val, 'confidence': 0.9} # Mock confidence
                except ValueError:
                    continue
        return {'value': 0.0, 'confidence': 0.0}

    def _extract_date(self, text: str, field_type: str) -> Dict[str, Any]:
        """Extract date"""
        for pattern in self.patterns.get(field_type, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                # Parse date
                dt = dateparser.parse(date_str)
                if dt:
                    return {'value': dt.strftime('%Y-%m-%d'), 'confidence': 0.85}
        return {'value': None, 'confidence': 0.0}

    def _extract_generic(self, text: str, field_type: str) -> Dict[str, Any]:
        """Extract generic string field"""
        for pattern in self.patterns.get(field_type, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return {'value': match.group(1).strip(), 'confidence': 0.8}
        return {'value': None, 'confidence': 0.0}

    def _extract_numeric(self, text: str, field_type: str) -> Dict[str, Any]:
        """Extract numeric field"""
        for pattern in self.patterns.get(field_type, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    val = float(match.group(1))
                    return {'value': val, 'confidence': 0.8}
                except ValueError:
                    continue
        return {'value': 0.0, 'confidence': 0.0}

    def _extract_biller_info(self, text: str) -> Dict[str, Any]:
        """Infer biller info from keywords"""
        text_lower = text.lower()
        
        if 'electricity' in text_lower or 'power' in text_lower or 'discom' in text_lower:
            return {'category': 'ELECTRICITY', 'biller_name': 'Detected Electricity Board', 'confidence': 0.8}
        elif 'water' in text_lower or 'jal' in text_lower:
            return {'category': 'WATER', 'biller_name': 'Detected Water Board', 'confidence': 0.8}
        elif 'gas' in text_lower or 'cylinder' in text_lower:
            return {'category': 'GAS', 'biller_name': 'Detected Gas Agency', 'confidence': 0.8}
        
        return {'category': 'OTHERS', 'biller_name': 'Unknown Biller', 'confidence': 0.5}
