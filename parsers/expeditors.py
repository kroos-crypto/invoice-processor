"""
Expeditors International parser.
Italian invoice format – often minimal data, no PO on invoice.
"""
import re
import pdfplumber
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date, clean_text


class ExpEditorsParser(BaseParser):
    name = 'Expeditors'

    def detect(self, text: str, filepath: str = '') -> bool:
        return 'Expeditors' in text or 'EXPEDITORS' in text

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        row = self.empty_row(filepath)
        row['dienstleister'] = 'Expeditors'

        # Rechnungsnummer: "Numero G406021836 del 26/02/26"
        m = re.search(r'Numero\s+([\w]+)\s+del\s+(\S+)', text)
        if m:
            row['rechnungsnr'] = m.group(1)
            row['rechnungsdatum'] = normalize_date(m.group(2))

        # Internal reference: "Ns.Rif. R4010652"
        m = re.search(r'Ns\.Rif\.?\s+([\w]+)', text)
        if m:
            row['trackingnummer'] = m.group(1)

        # Customer reference: "Vs.Rif." (may be empty → manual input needed)
        m = re.search(r'Vs\.Rif\.?\s+([\w/\-_]+)', text)
        row['referenz'] = clean_text(m.group(1)) if m else ''

        # Destination
        m = re.search(r'Destinazione\s+(\w+)', text)
        row['empfaenger_land'] = m.group(1) if m else ''

        # Pieces and volume
        m = re.search(r'(\d+)\s+PCS', text)
        row['anzahl_pakete'] = m.group(1) if m else ''

        m = re.search(r'([\d.]+)\s+CBM', text)
        row['gewicht_kg'] = ''  # no weight given

        # Service / charge description
        m = re.search(r'(OM CFS CHARGES|AIR FREIGHT|SEA FREIGHT|HANDLING[\w\s]+)', text)
        row['serviceart'] = clean_text(m.group(1)) if m else 'Diverse Charges'

        # Amount: "Totale Fattura: 16.99 EUR"
        m = re.search(r'Totale Fattura[:\s]+([\d.,]+)\s*EUR', text)
        if not m:
            m = re.search(r'SUMA[:\s]+([\d.,]+)', text)
        amount = normalize_number(m.group(1)) if m else None
        row['betrag_netto_eur'] = amount
        row['betrag_brutto_eur'] = amount
        row['rechnungsgesamtbetrag'] = amount

        # VAT: "REVERSE CHARGE" = no VAT charged (Reverse Charge)
        row['mwst_satz'] = '0 (Reverse Charge)'

        return [row]
