"""
UPS CSV Invoice Parser.
Handles UPS detail CSV exports (one row per charge line).
Columns are positional (no header row).

Key column indices (0-based):
  5  = invoice number
  9  = currency
 10  = invoice total
 11  = delivery date
 13  = waybill reference
 15  = OR/BL reference
 17  = incoterm
 18  = pieces
 20  = 1Z tracking number
 26  = weight
 27  = weight unit
 30  = packaging
 44  = charge type code  (FRT / BRK / GOV / EXM / FSC / ...)
 45  = charge sub-code   (008 / 405 / 410 / 201 / 1461 / ...)
 46  = charge description
 52  = amount A (netto for most types)
 53  = amount B (brutto / tax amount)
 57  = amount C (used by EXM / tax lines when col 50 is empty)
 69  = sender name
 75  = sender country
 77  = recipient name
 83  = recipient country
"""
import csv
from pathlib import Path
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date


# ── Charge-type → cost_label mapping ─────────────────────────────────────────
def _charge_label(code: str, sub: str, desc: str) -> str:
    """Produce a stable cost_label from UPS charge codes."""
    code = (code or '').strip()
    sub  = (sub  or '').strip()
    desc = (desc or '').strip()
    if code and sub:
        return f'{code}_{sub}'
    if code:
        return code
    return desc or 'UNKNOWN'


def _get_amount(cols: list, code: str) -> float | None:
    """Extract the relevant charge amount depending on charge type."""
    def _f(idx):
        try:
            v = normalize_number(cols[idx])
            return v if v and v != 0.0 else None
        except (IndexError, Exception):
            return None

    # EXM (tax/MwSt) rows have a shifted layout
    if code == 'EXM':
        return _f(57) or _f(56) or _f(55)

    # Normal rows: col 53 is the actual charge, col 52 is base/netto
    return _f(53) or _f(52) or _f(57)


class UPSCSVParser(BaseParser):
    name = 'UPS'

    def detect(self, text: str, filepath: str = '') -> bool:
        ext = Path(filepath).suffix.lower()
        if ext not in ('.csv',):
            return False
        # UPS CSV has no header row; first field is version "2.1"
        # and col 20 contains 1Z tracking numbers
        try:
            with open(filepath, encoding='utf-8-sig', errors='replace') as f:
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
            with open(filepath, encoding='utf-8-sig', errors='replace', newline='') as f:
                reader = csv.reader(f)
                for raw in reader:
                    if len(raw) < 47:
                        continue
                    if raw[0].strip() != '2.1':
                        continue

                    charge_code = raw[44].strip()
                    charge_sub  = raw[45].strip()
                    charge_desc = raw[46].strip()
                    amount      = _get_amount(raw, charge_code)

                    if amount is None or amount == 0.0:
                        continue  # skip zero-amount lines

                    row = self.empty_row(filepath)
                    row['dienstleister']        = 'UPS'
                    row['rechnungsnr']          = raw[5].strip().lstrip('0') or raw[5].strip()
                    row['rechnungsdatum']       = normalize_date(raw[4].strip())
                    row['trackingnummer']       = raw[20].strip()
                    row['referenz']             = raw[15].strip()
                    row['sendungsdatum']        = normalize_date(raw[11].strip())
                    row['incoterm']             = raw[17].strip()
                    row['anzahl_pakete']        = raw[18].strip()
                    row['gewicht_kg']           = normalize_number(raw[26].strip())
                    row['verpackungsart']       = raw[30].strip()
                    row['versender_name']       = raw[69].strip() if len(raw) > 69 else ''
                    row['versender_land']       = raw[75].strip() if len(raw) > 75 else ''
                    row['empfaenger_name']      = raw[77].strip() if len(raw) > 77 else ''
                    row['empfaenger_land']      = raw[83].strip() if len(raw) > 83 else ''
                    row['warenbeschreibung']    = raw[99].strip() if len(raw) > 99 else ''
                    row['serviceart']           = charge_desc or charge_code
                    row['cost_label']           = _charge_label(charge_code, charge_sub, charge_desc)
                    row['betrag_netto_eur']     = amount
                    row['betrag_brutto_eur']    = amount

                    # Total invoice amount (same for all rows of same invoice)
                    row['rechnungsgesamtbetrag'] = normalize_number(raw[10].strip())

                    rows.append(row)

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f'UPS CSV parse error: {e}')

        return rows
