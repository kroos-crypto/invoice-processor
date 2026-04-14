"""
FedEx CSV Invoice Parser.
Uses positional (index-based) reading because FedEx CSVs contain many
duplicate column names ("Luftfrachtbrief – Gebührenetikett" / "Gebührenbetrag"
repeated up to 50 times). csv.DictReader would silently drop all but the last.

Fixed column positions (verified against real export):
  0   Rechnungsland/-gebiet
  1   Rechnungsart
  5   FedEx Rechnungsnummer
  6   Rechnungsdatum
  7   Fälligkeitsdatum
  8   Rechnungswährung
  9   Gesamtbetrag Standardgebühren
 13   Fälliger ursprünglicher Betrag
 16   Luftfrachtbriefnummer
 18   Absenderreferenz 1
 19   Absenderreferenz 2
 24   Versanddatum (formatiert)
 27   Service
 28   Verpackung
 32   Stücke
 33   Tatsächliches Gewicht
 34   Tatsächliche Gewichtseinheiten
 38   Firma Absender
 46   Absenderadresse Land/Gebiet
 47   Firma Empfänger
 55   Empfängeradresse Land/Gebiet
 65   Luftfrachtbrief – Gesamtbetrag  (per-shipment total)
 66+  Alternating Gebührenetikett / Gebührenbetrag pairs
"""
import csv
from pathlib import Path
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date

# Fixed column indices
C_KUNDENNR      = 3
C_RECHNUNGSART  = 1
C_INVOICE_NR    = 5
C_INV_DATE      = 6
C_DUE_DATE      = 7
C_CURRENCY      = 8
C_TOTAL_STD     = 9
C_TOTAL_DUE     = 13
C_TRACKING      = 16
C_REF1          = 18
C_REF2          = 19
C_SHIP_DATE     = 24
C_SERVICE       = 27
C_PACKAGING     = 28
C_PIECES        = 32
C_WEIGHT        = 33
C_WEIGHT_UNIT   = 34
C_SENDER_NAME   = 38
C_SENDER_ORT    = 43
C_SENDER_PLZ    = 45
C_SENDER_LAND   = 46
C_RECV_NAME     = 47
C_RECV_ORT      = 52
C_RECV_PLZ      = 54
C_RECV_LAND     = 55
C_CHARGE_START  = 66   # first Gebührenetikett; +1 = Betrag, +2 = next Etikett, ...


def _col(row: list, idx: int, default: str = '') -> str:
    try:
        return row[idx].strip()
    except (IndexError, AttributeError):
        return default


class FedExCSVParser(BaseParser):
    name = 'FedEx'

    def detect(self, text: str, filepath: str = '') -> bool:
        if Path(filepath).suffix.lower() != '.csv':
            return False
        try:
            with open(filepath, encoding='utf-8-sig', errors='replace') as f:
                header = f.readline()
            return (
                'FedEx Rechnungsnummer' in header or
                'Luftfrachtbriefnummer' in header or
                'Rechnungsland/-gebiet' in header
            )
        except Exception:
            return False

    def parse_csv(self, filepath: str) -> list:
        rows = []
        try:
            with open(filepath, encoding='utf-8-sig', errors='replace', newline='') as f:
                reader = csv.reader(f)
                headers = next(reader)   # skip header row - we use fixed indices

                # Sanity check: need at least up to first charge pair
                if len(headers) < C_CHARGE_START:
                    return []

                for data in reader:
                    if not data or not _col(data, C_INVOICE_NR):
                        continue  # skip empty / summary rows

                    invoice_nr   = _col(data, C_INVOICE_NR)
                    kundennr     = _col(data, C_KUNDENNR)
                    inv_date     = normalize_date(_col(data, C_INV_DATE))
                    due_date     = normalize_date(_col(data, C_DUE_DATE))
                    currency     = _col(data, C_CURRENCY) or 'EUR'
                    total        = normalize_number(_col(data, C_TOTAL_DUE) or _col(data, C_TOTAL_STD))
                    tracking     = _col(data, C_TRACKING)
                    ref1         = _col(data, C_REF1)
                    ref2         = _col(data, C_REF2)
                    referenz     = ref1 or ref2
                    ship_date    = normalize_date(_col(data, C_SHIP_DATE))
                    service      = _col(data, C_SERVICE) or _col(data, C_RECHNUNGSART)
                    pieces       = _col(data, C_PIECES)
                    weight       = normalize_number(_col(data, C_WEIGHT))
                    packaging    = _col(data, C_PACKAGING)
                    sender_name  = _col(data, C_SENDER_NAME) or _col(data, 39)  # Firma or Ansprechpartner
                    sender_plz   = _col(data, C_SENDER_PLZ)
                    sender_ort   = _col(data, C_SENDER_ORT)
                    sender_land  = _col(data, C_SENDER_LAND)
                    recv_name    = _col(data, C_RECV_NAME) or _col(data, 48)
                    recv_plz     = _col(data, C_RECV_PLZ)
                    recv_ort     = _col(data, C_RECV_ORT)
                    recv_land    = _col(data, C_RECV_LAND)

                    # Walk all charge pairs starting at C_CHARGE_START
                    i = C_CHARGE_START
                    while i + 1 < len(data):
                        label  = _col(data, i)
                        amount = normalize_number(_col(data, i + 1))
                        i += 2

                        if not label or not amount or amount == 0.0:
                            continue

                        row = self.empty_row(filepath)
                        row['dienstleister']         = 'FedEx'
                        row['kundennummer']          = kundennr
                        row['rechnungsnr']           = invoice_nr
                        row['rechnungsdatum']        = inv_date
                        row['faelligkeitsdatum']     = due_date
                        row['rechnungsgesamtbetrag'] = total
                        row['trackingnummer']        = tracking
                        row['referenz']              = referenz
                        row['sendungsdatum']         = ship_date
                        row['serviceart']            = service
                        row['cost_label']            = label
                        row['incoterm']              = ''
                        row['versender_name']        = sender_name
                        row['versender_plz']         = sender_plz
                        row['versender_ort']         = sender_ort
                        row['versender_land']        = sender_land
                        row['empfaenger_name']       = recv_name
                        row['empfaenger_plz']        = recv_plz
                        row['empfaenger_ort']        = recv_ort
                        row['empfaenger_land']       = recv_land
                        row['warenbeschreibung']     = ''
                        row['gewicht_kg']            = weight
                        row['anzahl_pakete']         = pieces
                        row['verpackungsart']        = packaging
                        row['betrag_netto_eur']      = amount
                        row['betrag_brutto_eur']     = amount

                        rows.append(row)

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f'FedEx CSV parse error: {e}', exc_info=True)

        return rows
