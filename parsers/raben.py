"""
Raben Trans European Germany parser.
Invoice = summary page + Spezifikation pages (one shipment per block).
"""
import re
import pdfplumber
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date, clean_text


class RabenParser(BaseParser):
    name = 'Raben'

    def detect(self, text: str, filepath: str = '') -> bool:
        return 'Raben' in text and ('RABEN' in text or 'raben-group' in text)

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        rows = []

        # Header fields from full text
        m = re.search(r'RECHNUNGS-NR\.?[:\s]+([\d]+)', text)
        invoice_nr = m.group(1) if m else ''

        m = re.search(r'Rechnungsdatum[:\s]+(\d{4}-\d{2}-\d{2})', text)
        invoice_date = normalize_date(m.group(1)) if m else ''

        m = re.search(r'Leistungsdatum[:\s]+(\d{4}-\d{2}-\d{2})', text)
        service_date = normalize_date(m.group(1)) if m else ''

        m = re.search(r'Rechnungsbetrag[:\s]+([\d.,]+)\s*EUR', text)
        if not m:
            m = re.search(r'Total netto[:\s]+([\d.,]+)\s*EUR', text)
        total = normalize_number(m.group(1)) if m else None

        m = re.search(r'USt-Betrag\s+([\d.,]+)', text)
        vat_amount = normalize_number(m.group(1)) if m else None

        m = re.search(r'Zahlungsfrist[:\s]+(\d{4}-\d{2}-\d{2})', text)
        due_date = normalize_date(m.group(1)) if m else ''

        # Parse each shipment block from Spezifikation
        # Block pattern:
        # Abhol. | Sendung | Referenznummer | Zustell. | Inc | Anzahl | LDM | PP | CBM | KM
        # date   | sendnr  | refnr          | date     | DAP | n      | ...
        # Von: address
        # An: address
        # Aktivität | Bezeichnung | Betrag netto
        # nnn | Tagespreis Sammelgut EXP | ... | xx,xx EUR

        spez_re = re.compile(
            r'(\d{2}/\d{2}/\d{4})\s+'           # Abholdatum
            r'(\d{12,})\s+'                      # Sendungsnummer
            r'(\d{12,})\s+'                      # Referenznummer
            r'(\d{2}/\d{2}/\d{4})\s+'           # Zustelldatum
            r'(DAP|FOB|EXW|FCA|DDP|CPT|CIP)\s+' # Incoterm
            r'(\d+)',                             # Anzahl
            re.MULTILINE
        )

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                for m in spez_re.finditer(page_text):
                    row = self.empty_row(filepath)
                    row['dienstleister'] = 'Raben'
                    row['rechnungsnr'] = invoice_nr
                    row['rechnungsdatum'] = invoice_date
                    row['faelligkeitsdatum'] = due_date
                    row['rechnungsgesamtbetrag'] = total
                    row['sendungsdatum'] = normalize_date(m.group(1))
                    row['trackingnummer'] = m.group(2)
                    row['zustelldatum'] = normalize_date(m.group(4))
                    row['incoterm'] = m.group(5)
                    row['anzahl_pakete'] = m.group(6)
                    row['serviceart'] = 'Sammelgut'

                    # Extract context around this match for Von/An/Referenz/Cost
                    start = m.start()
                    context = page_text[start:start + 600]

                    # Kundenreferenz
                    ref_m = re.search(r'Kundenreferenz[:\s]+([\w\-_/]+)', context)
                    row['referenz'] = clean_text(ref_m.group(1)) if ref_m else m.group(3)

                    # Von (Versender)
                    von_m = re.search(r'Von[:\s]*\n?(.*?)(?:An[:\s]|\Z)', context, re.DOTALL)
                    if von_m:
                        von_lines = [l.strip() for l in von_m.group(1).splitlines() if l.strip()]
                        row['versender_name'] = von_lines[0] if von_lines else ''
                        row['versender_land'] = von_lines[-1] if len(von_lines) > 1 else ''

                    # An (Empfänger)
                    an_m = re.search(r'An[:\s]*\n?(.*?)(?:Aktivität|Bezeichnung|\Z)', context, re.DOTALL)
                    if an_m:
                        an_lines = [l.strip() for l in an_m.group(1).splitlines() if l.strip()]
                        row['empfaenger_name'] = an_lines[0] if an_lines else ''
                        row['empfaenger_land'] = an_lines[-1] if len(an_lines) > 1 else ''

                    # Cost: "Gesamt netto: XX,XX EUR"
                    cost_m = re.search(r'Gesamt netto[:\s]+([\d.,]+)\s*EUR', context)
                    if cost_m:
                        row['betrag_netto_eur'] = normalize_number(cost_m.group(1))
                        row['betrag_brutto_eur'] = normalize_number(cost_m.group(1))

                    row['mwst_satz'] = '19'
                    if row['betrag_netto_eur'] and vat_amount:
                        pass  # Could calculate proportional VAT

                    rows.append(row)

        # If no shipment blocks found (e.g. summary invoice only)
        if not rows:
            row = self.empty_row(filepath)
            row['dienstleister'] = 'Raben'
            row['rechnungsnr'] = invoice_nr
            row['rechnungsdatum'] = invoice_date
            row['faelligkeitsdatum'] = due_date
            row['rechnungsgesamtbetrag'] = total
            row['betrag_brutto_eur'] = total
            row['mwst_satz'] = '19'
            row['mwst_betrag_eur'] = vat_amount
            if total and vat_amount:
                row['betrag_netto_eur'] = round(total - vat_amount, 2)
            row['serviceart'] = 'Sammelgut Export'
            rows.append(row)

        return rows
