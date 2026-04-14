"""
UPS CSV Invoice Parser.
Handles UPS detail CSV exports (one row per charge line).
Columns are positional (no header row). Encoding: cp1252 (Windows Western European).

Key column indices (0-based):
  4  = invoice date
  5  = invoice number
 10  = invoice total
 11  = delivery date
 15  = OR/BL reference
 17  = incoterm
 18  = pieces
 20  = 1Z tracking number
 26  = weight
 30  = packaging
 44  = charge type code   (CIS / SCF / FSC / 003 / 069 / 201 / 410 / ...)
 45  = charge description ("Treibstoffzuschl.", "Zoll", "WW Expedited", ...)
 46  = internal sequence  (0000000 / 0000001 / ...)
 52  = charge amount
 67  = sender name        (only on Zoll/international invoices)
 70  = sender city
 72  = sender postal code
 73  = sender country
 75  = recipient name
 78  = recipient city
 80  = recipient postal code
 81  = recipient country
130  = goods description  (only on Zoll/international invoices)

Tax rows to skip: col44 == '01' (19% MwSt) or '1461' (Einfuhrumsatzsteuer)
cost_label = col45 (human-readable description) for rule matching in Kategorieregeln
"""
import csv
from pathlib import Path
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date

# Charge codes that represent MwSt / tax — skip entirely
TAX_CODES = {'01', '1461'}


def _get_amount(cols: list) -> float | None:
    """Extract the charge amount. Col52 is the primary amount field."""
    def _f(idx):
        try:
            v = normalize_number(cols[idx])
            return v if v and v != 0.0 else None
        except (IndexError, Exception):
            return None
    return _f(52) or _f(53) or _f(57)


class UPSCSVParser(BaseParser):
    name = 'UPS'

    def detect(self, text: str, filepath: str = '') -> bool:
        if Path(filepath).suffix.lower() != '.csv':
            return False
        # UPS CSV has no header row; first field is version "2.1"
        # and col 20 contains 1Z tracking numbers
        try:
            with open(filepath, encoding='cp1252', errors='replace') as f:
                first = f.readline()
            cols = first.split(',')
            return (
                cols[0].strip() == '2.1' and
                len(cols) > 44 and
                '1Z' in cols[20]
            )
        except Exception:
            return False

    def parse_csv(self, filepath: str) -> list:
        rows = []
        try:
            with open(filepath, encoding='cp1252', errors='replace', newline='') as f:
                reader = csv.reader(f)
                for raw in reader:
                    if len(raw) < 47:
                        continue
                    if raw[0].strip() != '2.1':
                        continue

                    charge_code = raw[44].strip()
                    charge_desc = raw[45].strip()   # human-readable description

                    # Skip MwSt / Tax rows entirely
                    if charge_code in TAX_CODES:
                        continue

                    amount = _get_amount(raw)
                    if not amount or amount == 0.0:
                        continue  # skip zero-amount lines

                    row = self.empty_row(filepath)
                    row['dienstleister']         = 'UPS'
                    row['rechnungsnr']           = raw[5].strip().lstrip('0') or raw[5].strip()
                    row['rechnungsdatum']        = normalize_date(raw[4].strip())
                    row['trackingnummer']        = raw[20].strip()
                    row['referenz']              = raw[15].strip()
                    row['sendungsdatum']         = normalize_date(raw[11].strip())
                    row['incoterm']              = raw[17].strip()
                    row['anzahl_pakete']         = raw[18].strip()
                    row['gewicht_kg']            = normalize_number(raw[26].strip())
                    row['verpackungsart']        = raw[30].strip()
                    row['versender_name']        = raw[67].strip()  if len(raw) > 67  else ''
                    row['versender_plz']         = raw[72].strip()  if len(raw) > 72  else ''
                    row['versender_ort']         = raw[70].strip()  if len(raw) > 70  else ''
                    row['versender_land']        = raw[73].strip()  if len(raw) > 73  else ''
                    row['empfaenger_name']       = raw[75].strip()  if len(raw) > 75  else ''
                    row['empfaenger_plz']        = raw[80].strip()  if len(raw) > 80  else ''
                    row['empfaenger_ort']        = raw[78].strip()  if len(raw) > 78  else ''
                    row['empfaenger_land']       = raw[81].strip()  if len(raw) > 81  else ''
                    row['warenbeschreibung']     = raw[130].strip() if len(raw) > 130 else ''
                    row['serviceart']            = charge_desc or charge_code
                    row['cost_label']            = charge_desc or charge_code  # description for Kategorieregeln
                    row['betrag_netto_eur']      = amount
                    row['betrag_brutto_eur']     = amount
                    row['rechnungsgesamtbetrag'] = normalize_number(raw[10].strip())

                    rows.append(row)

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f'UPS CSV parse error: {e}', exc_info=True)

        return rows
