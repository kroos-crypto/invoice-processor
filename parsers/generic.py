"""
Generic fallback parser.
Extracts whatever common fields it can find when no carrier-specific parser matched.
"""
import re
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date, clean_text


class GenericParser(BaseParser):
    name = 'Unbekannt'

    def detect(self, text: str, filepath: str = '') -> bool:
        # Always matches as last resort
        return True

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        row = self.empty_row(filepath)
        row['dienstleister'] = 'Unbekannt'

        # Try common German invoice patterns
        # Rechnungsnummer
        for pattern in [
            r'Rechnungs(?:nummer|nr\.?|No\.?)[:\s]+([A-Z0-9\-/]+)',
            r'Invoice\s*(?:No\.?|#)[:\s]+([A-Z0-9\-/]+)',
            r'Rechnung\s+Nr\.?\s*([A-Z0-9\-/]+)',
            r'R E C H N U N G\s+Nr\.?\s*([0-9]+)',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                row['rechnungsnr'] = m.group(1).strip()
                break

        # Rechnungsdatum
        for pattern in [
            r'Rechnungsdatum[:\s]+([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})',
            r'Invoice Date[:\s]+([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})',
            r'Datum[:\s]+([\d]{1,2}\.\d{2}\.\d{4})',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                row['rechnungsdatum'] = normalize_date(m.group(1))
                break

        # Fälligkeitsdatum
        for pattern in [
            r'Fälligkeits(?:datum)?[:\s]+([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})',
            r'Due Date[:\s]+([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})',
            r'Zahlbar bis[:\s]+([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})',
            r'Fällig bis[:\s]+([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                row['faelligkeitsdatum'] = normalize_date(m.group(1))
                break

        # Reference
        for pattern in [
            r'(?:Referenz|Reference|Ihre Referenz|Your Ref\.?)[:\s]+([A-Z0-9\-/_]+)',
            r'((?:OR|BL|PBL)\d{2}[\w]+)',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                row['referenz_1'] = clean_text(m.group(1))
                break

        # Total amount – try multiple patterns
        for pattern in [
            r'Gesamtbetrag\s+(?:EUR\s+)?([\d.,\s]+)',
            r'Total\s+(?:EUR\s+)?([\d.,\s]+)\s*EUR',
            r'Rechnungsbetrag\s+(?:EUR\s+)?([\d.,\s]+)',
            r'EUR\s+([\d.,\s]+)\s*$',
        ]:
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if m:
                val = normalize_number(m.group(1).replace(' ', ''))
                if val and val > 0:
                    row['rechnungsgesamtbetrag'] = val
                    row['betrag_brutto_eur'] = val
                    break

        # MwSt
        m = re.search(r'MwSt\.?\s+(\d+)\s*%', text)
        if m:
            row['mwst_satz'] = m.group(1)
        elif 'Reverse Charge' in text or 'reverse charge' in text.lower():
            row['mwst_satz'] = '0 (Reverse Charge)'

        m = re.search(r'MwSt\.?[:\s]+([\d.,]+)\s*EUR', text)
        if m:
            row['mwst_betrag_eur'] = normalize_number(m.group(1))

        # Weight
        m = re.search(r'([\d.,]+)\s*(?:kg|KG)\b', text)
        if m:
            row['gewicht_kg'] = normalize_number(m.group(1))

        return [row]
