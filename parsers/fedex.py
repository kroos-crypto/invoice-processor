"""
FedEx parsers:
  - FedExTransportParser  → "Rechnung- Fracht"
  - FedExZollParser       → "Rechnung Zoll und Steuer"
"""
import re
import pdfplumber
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date, clean_text


def _extract_fedex_header(text: str) -> dict:
    """Extract common FedEx invoice header fields."""
    header = {}

    m = re.search(r'Rechnungsnummer[:\s]+(\d+)', text)
    header['rechnungsnr'] = m.group(1) if m else ''

    m = re.search(r'Rechnungsdatum[:\s]+(\d{2}/\d{2}/\d{4})', text)
    header['rechnungsdatum'] = normalize_date(m.group(1)) if m else ''

    m = re.search(r'Fälligkeitsdatum[:\s]+(\S+)', text)
    header['faelligkeitsdatum'] = normalize_date(m.group(1)) if m else ''

    # Total – "Gesamt EUR 13 792,50" or "Fälliger Betrag ... 13 792,50 EUR"
    m = re.search(r'Gesamt\s+EUR\s+([\d\s.,]+)', text)
    if not m:
        m = re.search(r'Fälliger Betrag\s+([\d\s.,]+)\s*EUR', text)
    header['rechnungsgesamtbetrag'] = normalize_number(m.group(1).replace(' ', '')) if m else ''

    return header


# ──────────────────────────────────────────────────────────────────────────────
class FedExTransportParser(BaseParser):
    name = 'FedEx'

    def detect(self, text: str, filepath: str = '') -> bool:
        return 'FedEx' in text and ('Rechnung- Fracht' in text or 'Rechnung -Fracht' in text
                                    or 'Rechnung- Frach' in text)

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        rows = []
        header = _extract_fedex_header(text)

        # Each shipment block starts with a 12+-digit tracking number on a table row
        # Pattern captures: tracking | date | service | pieces | weight | reference | ... | amount
        shipment_re = re.compile(
            r'(\d{12,})\s+'                          # tracking number
            r'(\d{2}/\d{2}/\d{4})\s+'               # date
            r'(FedEx[^\n\d]{5,60?})\s+'             # service name
            r'(\d{1,3})\s+'                          # pieces
            r'([\d\s.,]+)\s*kg\s+'                   # weight
            r'([\w\s/\-_]{0,40}?)\s+'               # reference (can be empty)
            r'([\d\s.,]+)\s+'                        # taxable
            r'([\d\s.,]+)\s+'                        # tax-free
            r'([\d\s.,]+)',                          # amount
            re.MULTILINE | re.DOTALL
        )

        # Simpler fallback: just find tracking + date + amount blocks
        # We'll parse per page for better context
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                self._parse_page(page_text, header, rows, filepath)

        # If regex approach yielded nothing, create one summary row
        if not rows:
            row = self.empty_row(filepath)
            row.update(header)
            row['dienstleister'] = 'FedEx'
            rows.append(row)

        return rows

    def _parse_page(self, page_text: str, header: dict, rows: list, filepath: str):
        """Parse a single page for shipment blocks."""
        lines = page_text.split('\n')

        # Find lines with tracking numbers (12+ digit standalone number)
        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Tracking line: starts with long number + date
            m = re.match(
                r'^(\d{12,})\s+(\d{2}/\d{2}/\d{4})\s+(FedEx\s+\S.*?)\s+'
                r'(\d{1,3})\s+([\d.,\s]+)\s*(?:kg)?\s*'
                r'([\w\s/\-_]{0,40}?)\s+([\d.,\s]+)\s+([\d.,\s]+)\s+([\d.,\s]+)$',
                line
            )
            if m:
                row = self.empty_row(filepath)
                row.update(header)
                row['dienstleister'] = 'FedEx'
                row['trackingnummer'] = m.group(1)
                row['sendungsdatum'] = normalize_date(m.group(2))
                row['serviceart'] = clean_text(m.group(3))
                row['anzahl_pakete'] = m.group(4)
                row['gewicht_kg'] = normalize_number(m.group(5).replace(' ', ''))
                row['referenz'] = clean_text(m.group(6))
                amount = normalize_number(m.group(9).replace(' ', ''))
                row['betrag_netto_eur'] = amount
                row['betrag_brutto_eur'] = amount

                # Look ahead for sender/recipient (next ~5 lines)
                sender_lines, recv_lines = [], []
                for j in range(i + 1, min(i + 10, len(lines))):
                    nxt = lines[j].strip()
                    if not nxt:
                        continue
                    # "Versender" / "Empfänger" header line
                    if re.match(r'^(Versender|Empfänger)', nxt):
                        continue
                    # Line with "Betrag EUR" signals end of block
                    if 'Betrag EUR' in nxt:
                        betrag_m = re.search(r'Betrag EUR\s+([\d.,\s]+)', nxt)
                        if betrag_m:
                            row['betrag_netto_eur'] = normalize_number(betrag_m.group(1).replace(' ', ''))
                        break
                    # Alternate sender/receiver columns
                    if len(sender_lines) <= len(recv_lines):
                        sender_lines.append(nxt)
                    else:
                        recv_lines.append(nxt)

                row['versender_name'] = sender_lines[0] if sender_lines else ''
                row['versender_land'] = sender_lines[-1] if len(sender_lines) > 1 else ''
                row['empfaenger_name'] = recv_lines[0] if recv_lines else ''
                row['empfaenger_land'] = recv_lines[-1] if len(recv_lines) > 1 else ''

                rows.append(row)
            i += 1


# ──────────────────────────────────────────────────────────────────────────────
class FedExZollParser(BaseParser):
    name = 'FedEx'

    def detect(self, text: str, filepath: str = '') -> bool:
        return 'FedEx' in text and 'Zoll und Steuer' in text

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        rows = []
        header = _extract_fedex_header(text)

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                self._parse_page(page_text, header, rows, filepath)

        if not rows:
            row = self.empty_row(filepath)
            row.update(header)
            row['dienstleister'] = 'FedEx'
            row['serviceart'] = 'Zoll und Steuer'
            rows.append(row)

        return rows

    def _parse_page(self, page_text: str, header: dict, rows: list, filepath: str):
        lines = page_text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Tracking line for Zoll invoice: tracking | date | service | reference | Zölle | ... | Betrag
            m = re.match(
                r'^(\d{12,})\s+(\d{2}/\d{2}/\d{4})\s+([\w\s]+?Service)\s+'
                r'(\d+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)$',
                line
            )
            if m:
                row = self.empty_row(filepath)
                row.update(header)
                row['dienstleister'] = 'FedEx'
                row['trackingnummer'] = m.group(1)
                row['sendungsdatum'] = normalize_date(m.group(2))
                row['serviceart'] = clean_text(m.group(3))
                row['referenz'] = clean_text(m.group(4))
                row['betrag_netto_eur'] = normalize_number(m.group(9))
                row['betrag_brutto_eur'] = normalize_number(m.group(9))
                row['mwst_satz'] = '19'

                # Look ahead for sender/recipient
                for j in range(i + 1, min(i + 8, len(lines))):
                    nxt = lines[j].strip()
                    if 'Versender' in nxt and not row['versender_name']:
                        pass
                    if 'Betrag EUR' in nxt:
                        bm = re.search(r'Betrag EUR\s+([\d.,\s]+)', nxt)
                        if bm:
                            row['betrag_brutto_eur'] = normalize_number(bm.group(1).replace(' ', ''))
                        break
                    if not row['versender_name'] and nxt and not re.match(r'^(Versender|Empfänger|Kosten|Zölle)', nxt):
                        row['versender_name'] = nxt
                    elif not row['empfaenger_name'] and nxt and not re.match(r'^(Versender|Empfänger|Kosten|Zölle|Aufwendung)', nxt):
                        row['empfaenger_name'] = nxt

                rows.append(row)
            i += 1
