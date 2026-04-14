"""
UPS CSV Invoice Parser.
Handles UPS detail CSV exports (one row per charge line, no header row).
Encoding: cp1252 (Windows Western European).

Key column indices (0-based):
  0   Version marker ("2.1")
  1   Kundennummer
  4   Rechnungsdatum
  5   Rechnungsnummer
 10   Rechnungsgesamtbetrag
 11   Sendungsdatum
 15   Referenz 1 (OR / BL / PBL reference)
 16   Referenz 2 (order number)
 20   1Z Trackingnummer
 26   Ist-Gewicht
 27   Gewichtseinheit
 43   Charge-Kategorie  (FRT / ACC / TAX / …)
 44   Charge-Code       (003 / SCF / ASW / CIS / 01 / …)
 45   Charge-Beschreibung ("Dom. Standard", "Treibstoffzuschlag", …)
 46   Interne Sequenz
 52   Betrag (EUR)
 66   Versender – Ansprechpartner
 67   Versender – Firma
 68   Versender – Straße
 70   Versender – Ort
 72   Versender – PLZ
 73   Versender – Land
 74   Empfänger – Ansprechpartner
 75   Empfänger – Firma
 78   Empfänger – Ort
 80   Empfänger – PLZ
 81   Empfänger – Land
130   Warenbeschreibung

Row structure: every row is one charge line. No separate sub-rows.
Service type is derived from the FRT category row for each tracking number
(two-pass approach: first build a tracking→service map, then produce output rows).

Tax rows to skip: charge code 01 (19 % MwSt) or 1461 (Einfuhrumsatzsteuer).
"""
import csv
from pathlib import Path
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date

# Charge codes that represent MwSt / tax – skip entirely
TAX_CODES = {'01', '1461'}


def _get_amount(cols: list) -> float | None:
    """Extract charge amount. Col 52 is primary; fall back to 53 or 57."""
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
            # ── Read all data rows ────────────────────────────────────────────
            all_data = []
            with open(filepath, encoding='cp1252', errors='replace', newline='') as f:
                reader = csv.reader(f)
                for raw in reader:
                    if len(raw) < 47:
                        continue
                    if raw[0].strip() != '2.1':
                        continue
                    charge_code = raw[44].strip()
                    if charge_code in TAX_CODES:
                        continue
                    all_data.append(raw)

            # ── Pass 1: build tracking → service type map ─────────────────────
            # The FRT (freight) category row describes the overall service
            service_map: dict[str, str] = {}
            for raw in all_data:
                tracking  = raw[20].strip()
                category  = raw[43].strip()  # FRT / ACC / TAX …
                charge_desc = raw[45].strip()
                if category == 'FRT' and tracking and tracking not in service_map:
                    service_map[tracking] = charge_desc

            # ── Pass 2: emit output rows ──────────────────────────────────────
            for raw in all_data:
                charge_code = raw[44].strip()
                charge_desc = raw[45].strip()

                amount = _get_amount(raw)
                if not amount or amount == 0.0:
                    continue

                tracking = raw[20].strip()
                ref1     = raw[15].strip()
                ref2     = raw[16].strip() if len(raw) > 16 else ''

                row = self.empty_row(filepath)
                row['dienstleister']         = 'UPS'
                row['kundennummer']          = raw[1].strip().lstrip('0') or raw[1].strip()
                row['rechnungsnr']           = raw[5].strip().lstrip('0') or raw[5].strip()
                row['rechnungsdatum']        = normalize_date(raw[4].strip())
                row['trackingnummer']        = tracking
                row['referenz_1']            = ref1
                row['referenz_2']            = ref2
                row['sendungsdatum']         = normalize_date(raw[11].strip())
                row['serviceart']            = service_map.get(tracking, '')
                row['cost_label']            = charge_desc or charge_code
                row['incoterm']              = raw[17].strip() if len(raw) > 17 else ''
                row['anzahl_pakete']         = raw[18].strip() if len(raw) > 18 else ''
                row['gewicht_kg']            = normalize_number(raw[26].strip())
                row['gewicht_einheit']       = raw[27].strip() if len(raw) > 27 else ''
                row['verpackungsart']        = raw[30].strip() if len(raw) > 30 else ''
                row['versender_name']        = raw[67].strip() if len(raw) > 67 else ''
                row['versender_plz']         = raw[72].strip() if len(raw) > 72 else ''
                row['versender_ort']         = raw[70].strip() if len(raw) > 70 else ''
                row['versender_land']        = raw[73].strip() if len(raw) > 73 else ''
                row['empfaenger_name']       = raw[75].strip() if len(raw) > 75 else ''
                row['empfaenger_plz']        = raw[80].strip() if len(raw) > 80 else ''
                row['empfaenger_ort']        = raw[78].strip() if len(raw) > 78 else ''
                row['empfaenger_land']       = raw[81].strip() if len(raw) > 81 else ''
                row['warenbeschreibung']     = raw[130].strip() if len(raw) > 130 else ''
                row['betrag_netto_eur']      = amount
                row['betrag_brutto_eur']     = amount
                row['rechnungsgesamtbetrag'] = normalize_number(raw[10].strip())

                rows.append(row)

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f'UPS CSV parse error: {e}', exc_info=True)

        return rows
