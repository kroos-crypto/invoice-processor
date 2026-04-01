"""
UPS parsers:
  - UPSTransportParser  → large transport invoice (Frachtbriefe Innerdeutsch/EU/Returns)
  - UPSZollParser       → import customs invoice (Sendungs-Detail with Zoll)
  - UPSAbholParser      → pickup-only invoice (Importsendung-Details / Abholauftrag)
"""
import re
import pdfplumber
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date, clean_text


def _extract_ups_header(text: str) -> dict:
    header = {}

    m = re.search(r'Rechnungsnr\.?[:\s]+(\d+)', text)
    header['rechnungsnr'] = m.group(1) if m else ''

    m = re.search(r'Rechnungsdatum\s+(\d{2}\.\S+\s+\d{4})', text)
    header['rechnungsdatum'] = normalize_date(m.group(1)) if m else ''

    # "Fälliger Gesamtbetrag EUR 5.550,33" or "EUR   35.648,01"
    m = re.search(r'Fälliger Gesamtbetrag\s+EUR\s+([\d.,\s]+)', text)
    if not m:
        m = re.search(r'EUR\s+([\d.,\s]+)\s*$', text, re.MULTILINE)
    header['rechnungsgesamtbetrag'] = normalize_number(m.group(1).replace(' ', '')) if m else ''

    return header


# ──────────────────────────────────────────────────────────────────────────────
class UPSTransportParser(BaseParser):
    name = 'UPS'

    def detect(self, text: str, filepath: str = '') -> bool:
        return ('United Parcel Service' in text or 'UPS' in text) and (
            'Frachtbrief' in text or 'Sendungs' in text
        ) and 'Zoll' not in text[:500] and 'Abholauftrag' not in text[:1000]

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        rows = []
        header = _extract_ups_header(text)

        with pdfplumber.open(filepath) as pdf:
            # UPS can be 85 pages – iterate and detect section per page
            current_section = 'Transport'
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                self._parse_page(page_text, header, rows, filepath, current_section)

        if not rows:
            row = self.empty_row(filepath)
            row.update(header)
            row['dienstleister'] = 'UPS'
            rows.append(row)

        return rows

    def _parse_page(self, page_text: str, header: dict, rows: list,
                    filepath: str, section: str):
        lines = page_text.split('\n')

        for i, line in enumerate(lines):
            line = line.strip()

            # UPS Frachtbrief lines start with a date + tracking pattern
            # "05.Jan  1Z588Y666801897120  PBL25TCCE0021  Dom. Standard  10  311,85  190,23  121,62"
            m = re.match(
                r'^(\d{1,2}\.\w{3})\s+'         # date (e.g. 05.Jan)
                r'(1Z\w{16})\s+'                # UPS tracking (1Z...)
                r'([\w/\-_]+(?:\s+[\w/\-_]+)?)\s+' # reference(s)
                r'([\w\s.]+?)\s+'               # service type
                r'(\d+)\s+'                     # packages
                r'([\d.,]+)\s+'                 # tarif
                r'([\d.,]+)\s+'                 # rabatt
                r'([\d.,]+)$',                  # nettotarif
                line
            )
            if m:
                row = self.empty_row(filepath)
                row.update(header)
                row['dienstleister'] = 'UPS'
                row['sendungsdatum'] = normalize_date(m.group(1))
                row['trackingnummer'] = m.group(2)
                row['referenz'] = clean_text(m.group(3))
                row['serviceart'] = clean_text(m.group(4))
                row['anzahl_pakete'] = m.group(5)
                row['betrag_netto_eur'] = normalize_number(m.group(8))
                rows.append(row)
                continue

            # Abholauftrag lines in Korrekturen section
            # "05.Jan  05.Jan  29HDSJ5EQ2B  BL25TCLB0004_3  1Z588Y666826841464"
            m2 = re.match(
                r'^(\d{1,2}\.\w{3})\s+(\d{1,2}\.\w{3})\s+'
                r'([0-9A-F]{10,})\s+'           # Abholauftragsnummer
                r'([\w/\-_]+(?:\s+[\w/\-_]+)?)\s+'  # reference
                r'(1Z\w{16})',                  # frachtbrief
                line
            )
            if m2:
                row = self.empty_row(filepath)
                row.update(header)
                row['dienstleister'] = 'UPS'
                row['sendungsdatum'] = normalize_date(m2.group(1))
                row['trackingnummer'] = m2.group(5)
                row['referenz'] = clean_text(m2.group(4))
                row['serviceart'] = 'Abholauftrag'

                # Get cost from next lines
                for j in range(i + 1, min(i + 5, len(lines))):
                    cost_m = re.search(r'([\d.,]+)\s+([\d.,]+)$', lines[j].strip())
                    if cost_m:
                        row['betrag_netto_eur'] = normalize_number(cost_m.group(2))
                        break
                rows.append(row)


# ──────────────────────────────────────────────────────────────────────────────
class UPSZollParser(BaseParser):
    name = 'UPS'

    def detect(self, text: str, filepath: str = '') -> bool:
        return ('United Parcel Service' in text or 'UPS' in text) and (
            'Import Tarif' in text or 'Importzoll' in text or 'Sendungs - Detail' in text
        ) and 'Abholauftrag' not in text[:500]

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        rows = []
        header = _extract_ups_header(text)

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                self._parse_page(page_text, header, rows, filepath)

        if not rows:
            row = self.empty_row(filepath)
            row.update(header)
            row['dienstleister'] = 'UPS'
            row['serviceart'] = 'Zoll / Import Tarif'
            rows.append(row)

        return rows

    def _parse_page(self, page_text: str, header: dict, rows: list, filepath: str):
        lines = page_text.split('\n')

        for i, line in enumerate(lines):
            line = line.strip()

            # Shipment detail line:
            # "22.Jan  1Z588Y666700101303  OR25RLAI1473_1_1069 840  WW Expedited  3  90,0/102,5  PKG  B"
            m = re.match(
                r'^(\d{1,2}\.\w{3})\s+'         # export date
                r'(1Z\w{16})\s+'                # tracking
                r'([\w/\-_\s]+?)\s+'            # reference
                r'(WW|TB|Dom\.)[\w\s]+\s+'      # service prefix
                r'(\d+)\s+'                     # packages
                r'([\d.,/]+)',                  # weight
                line
            )
            if m:
                row = self.empty_row(filepath)
                row.update(header)
                row['dienstleister'] = 'UPS'
                row['sendungsdatum'] = normalize_date(m.group(1))
                row['trackingnummer'] = m.group(2)
                row['referenz'] = clean_text(m.group(3))
                row['serviceart'] = 'WW Expedited / Zoll'
                row['anzahl_pakete'] = m.group(5)
                wt = m.group(6).split('/')[0]
                row['gewicht_kg'] = normalize_number(wt)

                # Look ahead for description and amounts
                for j in range(i + 1, min(i + 15, len(lines))):
                    nxt = lines[j].strip()

                    # Description line
                    if re.match(r'^[A-Z]{2,}', nxt) and not re.match(
                            r'^(Versender|Empfänger|Zahler|Beschreibung|Shipment|Import|Export|Bemerk)', nxt):
                        if not row['warenbeschreibung']:
                            row['warenbeschreibung'] = clean_text(nxt)

                    # Sender
                    if nxt.startswith('Versender:'):
                        row['versender_name'] = nxt.replace('Versender:', '').strip()
                    if nxt.startswith('Empfänger:'):
                        row['empfaenger_name'] = nxt.replace('Empfänger:', '').strip()

                    # Total line: "Gesamtbetrag EUR 183,79 7,27 176,52"
                    gm = re.match(r'^Gesamtbetrag\s+EUR\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)', nxt)
                    if gm:
                        row['betrag_netto_eur'] = normalize_number(gm.group(3))  # Nettotarif
                        row['betrag_brutto_eur'] = normalize_number(gm.group(3))
                        break

                rows.append(row)


# ──────────────────────────────────────────────────────────────────────────────
class UPSAbholParser(BaseParser):
    name = 'UPS'

    def detect(self, text: str, filepath: str = '') -> bool:
        return ('United Parcel Service' in text or 'UPS' in text) and (
            'Abholauftrag' in text and 'Importsendung' in text
        )

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        rows = []
        header = _extract_ups_header(text)

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                self._parse_page(page_text, header, rows, filepath)

        if not rows:
            row = self.empty_row(filepath)
            row.update(header)
            row['dienstleister'] = 'UPS'
            row['serviceart'] = 'Abholgebühren'
            rows.append(row)

        return rows

    def _parse_page(self, page_text: str, header: dict, rows: list, filepath: str):
        lines = page_text.split('\n')

        for i, line in enumerate(lines):
            line = line.strip()

            # Abholauftrag lines:
            # "18.Feb  18.Feb  292B4EB4F3C  V588Y478674  BL25FLAT0002_6  1Z588Y669134478674"
            m = re.match(
                r'^(\d{1,2}\.\w{3})\s+(\d{1,2}\.\w{3})\s+'
                r'([0-9A-F]{10,})\s+'            # pickup order number
                r'(\w+)\s+'                      # ref 1
                r'([\w/\-_]+(?:\s+[\w/\-_]+)?)\s*'  # ref 2 (optional)
                r'(1Z\w{16})?',                  # frachtbrief (optional)
                line
            )
            if m:
                row = self.empty_row(filepath)
                row.update(header)
                row['dienstleister'] = 'UPS'
                row['sendungsdatum'] = normalize_date(m.group(1))
                row['zustelldatum'] = normalize_date(m.group(2))
                row['trackingnummer'] = m.group(6) or m.group(3)
                # Combine refs
                refs = [r for r in [m.group(4), m.group(5)] if r and r != m.group(6)]
                row['referenz'] = ' / '.join(clean_text(r) for r in refs)
                row['serviceart'] = 'Abholgebühr'

                # Sender from next line
                for j in range(i + 1, min(i + 3, len(lines))):
                    nxt = lines[j].strip()
                    if nxt and not re.match(r'^\d', nxt):
                        row['versender_name'] = nxt
                        break

                # Cost from "Gesamtkosten ... EUR X,XX X,XX"
                for j in range(i + 1, min(i + 6, len(lines))):
                    nxt = lines[j].strip()
                    cm = re.search(r'EUR\s+([\d.,]+)\s+([\d.,]+)$', nxt)
                    if cm:
                        row['betrag_netto_eur'] = normalize_number(cm.group(2))
                        row['betrag_brutto_eur'] = normalize_number(cm.group(2))
                        break

                rows.append(row)
