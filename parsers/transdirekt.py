"""
Transdirekt Eurologistik parser.
Single-page invoices with Ladestelle / Entladestelle structure.
"""
import re
import pdfplumber
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date, clean_text


class TransdirektParser(BaseParser):
    name = 'Transdirekt'

    def detect(self, text: str, filepath: str = '') -> bool:
        return 'Transdirekt' in text or 'transdirekt' in text

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        row = self.empty_row(filepath)
        row['dienstleister'] = 'Transdirekt Eurologistik'

        # Rechnungsnummer
        m = re.search(r'Rechnung Nr\.?[:\s]+(\d+)', text)
        if not m:
            m = re.search(r'R E C H N U N G\s*\n[\s\S]{0,100}?(\d{4,})', text)
        row['rechnungsnr'] = m.group(1) if m else ''

        # Date
        m = re.search(r'Datum[:\s]+(\d{2}\.\d{2}\.\d{4})', text)
        row['rechnungsdatum'] = normalize_date(m.group(1)) if m else ''

        # Reference / PO
        m = re.search(r'Referenz[:\s]+([\w/\-_]+)', text)
        if not m:
            m = re.search(r'(BL\d{2}\w+|PBL\d{2}\w+|OR\d{2}\w+)', text)
        row['referenz'] = clean_text(m.group(1)) if m else ''

        # Incoterm
        m = re.search(r'(EXW|FCA|FOB|CPT|CIP|DAP|DDP|DDU|FAS|CFR|CIF)', text)
        row['incoterm'] = m.group(1) if m else ''

        # Pickup / delivery dates
        m = re.search(r'Abholdatum\s+(\d{2}\.\d{2}\.\d{4})', text)
        row['sendungsdatum'] = normalize_date(m.group(1)) if m else ''

        m = re.search(r'Anlieferdatum\s+(\d{2}\.\d{2}\.\d{4})', text)
        row['zustelldatum'] = normalize_date(m.group(1)) if m else ''

        # Due date
        m = re.search(r'Fällig bis[:\s]+(\d{2}\.\d{2}\.\d{2,4})', text)
        row['faelligkeitsdatum'] = normalize_date(m.group(1)) if m else ''

        # Ladestelle (Versender)
        m = re.search(r'Ladestelle\s*\n([\s\S]{10,120}?)(?:Entladestelle|Kennzeichen)', text)
        if m:
            lines = [l.strip() for l in m.group(1).splitlines() if l.strip()]
            row['versender_name'] = lines[0] if lines else ''
            row['versender_land'] = lines[-1] if len(lines) > 1 else ''

        # Entladestelle (Empfänger)
        m = re.search(r'Entladestelle\s*\n([\s\S]{10,120}?)(?:Kennzeichen|Markierung)', text)
        if m:
            lines = [l.strip() for l in m.group(1).splitlines() if l.strip()]
            row['empfaenger_name'] = lines[0] if lines else ''
            row['empfaenger_land'] = lines[-1] if len(lines) > 1 else ''

        # Weight and pieces
        m = re.search(r'(\d[\d.,]+)\s*(?:kg|KG)', text)
        row['gewicht_kg'] = normalize_number(m.group(1)) if m else ''

        # Packaging: Kartons / Paletten
        packs = re.findall(r'(\d+)\s+(KARTONS|PALETTE|PAKET|PKG|STK)', text, re.IGNORECASE)
        if packs:
            row['anzahl_pakete'] = ' + '.join(f'{p[0]} {p[1]}' for p in packs)
            row['verpackungsart'] = packs[0][1].capitalize() if packs else ''

        # Netto amount (before VAT)
        m = re.search(r'MwSt\.-Pfl\.?[:\s]+([\d.,]+)', text)
        row['betrag_netto_eur'] = normalize_number(m.group(1)) if m else ''

        # VAT
        m = re.search(r'MwSt\.[:\s]+([\d.,]+)', text)
        row['mwst_betrag_eur'] = normalize_number(m.group(1)) if m else ''

        # Total (Gesamtbetrag)
        m = re.search(r'Gesamtbetrag\s*\n?EUR\s+([\d.,]+)', text)
        if not m:
            m = re.search(r'EUR\s+([\d\s.,]+)\s*$', text, re.MULTILINE)
        total = normalize_number(m.group(1).replace(' ', '')) if m else None
        row['betrag_brutto_eur'] = total
        row['rechnungsgesamtbetrag'] = total

        row['mwst_satz'] = '19' if row['betrag_netto_eur'] else '0'
        row['serviceart'] = 'Frachtkosten Sammelgut'

        return [row]
