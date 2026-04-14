"""
Logfret parser.
Air freight / customs invoices – AWB-based structure.
"""
import re
import pdfplumber
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date, clean_text


class LogfretParser(BaseParser):
    name = 'Logfret'

    def detect(self, text: str, filepath: str = '') -> bool:
        return 'Logfret' in text or 'LOGFRET' in text

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        rows = []

        # Header: invoice number and date
        m = re.search(r'(?:Invoice|Rechnung|INVOICE)\s*(?:No\.?|Nr\.?|#)?\s*[:\s]+([A-Z0-9\-/]+)', text)
        invoice_nr = m.group(1).strip() if m else ''

        m = re.search(r'(?:Invoice Date|Rechnungsdatum|Date)[:\s]+([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})', text)
        invoice_date = normalize_date(m.group(1)) if m else ''

        m = re.search(r'(?:Due Date|Fällig|Payment Terms)[:\s]+([\d]{1,2}[./\-][\d]{1,2}[./\-][\d]{2,4})', text)
        due_date = normalize_date(m.group(1)) if m else ''

        # Total amount
        m = re.search(r'(?:Total|TOTAL|Gesamt)[:\s]+(?:EUR|USD)?\s*([\d.,\s]+)\s*(?:EUR|USD)?', text)
        if not m:
            m = re.search(r'(?:Amount Due|Zahlbetrag)[:\s]+(?:EUR)?\s*([\d.,\s]+)', text)
        total = normalize_number(m.group(1).replace(' ', '')) if m else None

        # Try to extract per-AWB rows from Spezifikation / detail section
        # AWB pattern: 123-12345678 or 12312345678
        awb_re = re.compile(
            r'(\d{3}-?\d{8})\s+'           # AWB number
            r'([\d]{1,2}[./][\d]{1,2}[./][\d]{2,4})?\s*'  # date (optional)
            r'([A-Z]{2,3})\s+'             # origin airport code
            r'([A-Z]{2,3})\s+'             # destination airport code
            r'(\d+)\s+'                    # pieces
            r'([\d.,]+)\s*(?:kg|KG)',      # weight
            re.MULTILINE
        )

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                for m in awb_re.finditer(page_text):
                    row = self.empty_row(filepath)
                    row['dienstleister'] = 'Logfret'
                    row['rechnungsnr'] = invoice_nr
                    row['rechnungsdatum'] = invoice_date
                    row['faelligkeitsdatum'] = due_date
                    row['rechnungsgesamtbetrag'] = total
                    row['trackingnummer'] = m.group(1).replace('-', '')
                    if m.group(2):
                        row['sendungsdatum'] = normalize_date(m.group(2))
                    row['versender_land'] = m.group(3)   # origin IATA code
                    row['empfaenger_land'] = m.group(4)  # dest IATA code
                    row['anzahl_pakete'] = m.group(5)
                    row['gewicht_kg'] = normalize_number(m.group(6))
                    row['serviceart'] = 'Air Freight'
                    row['mwst_satz'] = '0 (Reverse Charge)'

                    # Look for reference in surrounding context
                    start = m.start()
                    ctx = page_text[max(0, start - 100):start + 400]
                    ref_m = re.search(r'(?:Reference|Referenz|Your Ref\.?|Ref\.?)[:\s]+([A-Z]{2}[\d\w]+)', ctx, re.IGNORECASE)
                    if ref_m:
                        row['referenz_1'] = clean_text(ref_m.group(1))

                    # Amount for this AWB
                    amt_m = re.search(r'(?:EUR|USD)\s*([\d.,]+)\s*(?:EUR)?', ctx[ctx.find(m.group(1)):])
                    if amt_m:
                        row['betrag_netto_eur'] = normalize_number(amt_m.group(1))
                        row['betrag_brutto_eur'] = normalize_number(amt_m.group(1))

                    rows.append(row)

        # Fallback: single summary row if no AWB blocks found
        if not rows:
            row = self.empty_row(filepath)
            row['dienstleister'] = 'Logfret'
            row['rechnungsnr'] = invoice_nr
            row['rechnungsdatum'] = invoice_date
            row['faelligkeitsdatum'] = due_date
            row['rechnungsgesamtbetrag'] = total
            row['betrag_netto_eur'] = total
            row['betrag_brutto_eur'] = total
            row['mwst_satz'] = '0 (Reverse Charge)'
            row['serviceart'] = 'Air Freight'

            # Try to get reference
            ref_m = re.search(r'(?:Reference|Referenz|Your Ref\.?)[:\s]+([A-Z]{2}[\d\w]+)', text, re.IGNORECASE)
            row['referenz_1'] = clean_text(ref_m.group(1)) if ref_m else ''

            rows.append(row)

        return rows
