"""
FedEx CSV Invoice Parser.
Handles FedEx detail CSV exports (Zoll/Steuer and Rechnung-Fracht).
Row 1 is the header row with German column names.
Charge labels and amounts appear as alternating pairs starting
at column "Luftfrachtbrief – Gebührenetikett" / "Luftfrachtbrief – Gebührenbetrag".
"""
import csv
from pathlib import Path
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date


class FedExCSVParser(BaseParser):
    name = 'FedEx'

    def detect(self, text: str, filepath: str = '') -> bool:
        ext = Path(filepath).suffix.lower()
        if ext not in ('.csv',):
            return False
        try:
            with open(filepath, encoding='utf-8-sig', errors='replace') as f:
                header = f.readline()
            return (
                'FedEx Rechnungsnummer' in header or
                'Luftfrachtbriefnummer' in header or
                'Rechnungsland' in header
            )
        except Exception:
            return False

    def parse_csv(self, filepath: str) -> list:
        rows = []
        try:
            with open(filepath, encoding='utf-8-sig', errors='replace', newline='') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []

                # Find charge label/amount column pairs
                label_cols = [h for h in headers if 'Gebührenetikett' in h or 'Gebuehrenetikett' in h]
                amount_cols = [h for h in headers if 'Gebührenbetrag' in h or 'Gebuehrenbetrag' in h]
                charge_pairs = list(zip(label_cols, amount_cols))

                # Detect invoice type (Transport vs Zoll)
                rechnungsart_col = next(
                    (h for h in headers if 'Rechnungsart' in h), None
                )

                for data in reader:
                    invoice_nr  = data.get('FedEx Rechnungsnummer', '').strip()
                    inv_date    = normalize_date(data.get('Rechnungsdatum', '').strip())
                    due_date    = normalize_date(data.get('Fälligkeitsdatum', '').strip())
                    currency    = data.get('Rechnungswährung', 'EUR').strip()
                    total       = normalize_number(data.get('Fälliger ursprünglicher Betrag', '') or
                                                   data.get('Gesamtbetrag Standardgebühren', ''))
                    tracking    = data.get('Luftfrachtbriefnummer', '').strip()
                    ref1        = data.get('Absenderreferenz 1', '').strip()
                    ref2        = data.get('Absenderreferenz 2', '').strip()
                    referenz    = ref1 or ref2
                    ship_date   = normalize_date(data.get('Versanddatum (formatiert)', '').strip())
                    service     = data.get('Service', '').strip()
                    pieces      = data.get('Stücke', '').strip()
                    weight      = normalize_number(data.get('Tatsächliches Gewicht', ''))
                    weight_unit = data.get('Tatsächliche Gewichtseinheiten', '').strip()
                    packaging   = data.get('Verpackung', '').strip()
                    sender_name = data.get('Firma Absender', '').strip()
                    sender_land = data.get('Absenderadresse Land/Gebiet', '').strip()
                    recv_name   = data.get('Firma Empfänger', '').strip()
                    recv_land   = data.get('Empfängeradresse Land/Gebiet', '').strip()
                    goods_desc  = ''  # not in FedEx CSV

                    rechnungsart = data.get(rechnungsart_col, '').strip() if rechnungsart_col else ''

                    # Create one row per charge label/amount pair (non-zero)
                    for label_col, amount_col in charge_pairs:
                        label  = data.get(label_col, '').strip()
                        amount = normalize_number(data.get(amount_col, ''))

                        if not label or not amount or amount == 0.0:
                            continue

                        row = self.empty_row(filepath)
                        row['dienstleister']         = 'FedEx'
                        row['rechnungsnr']           = invoice_nr
                        row['rechnungsdatum']        = inv_date
                        row['faelligkeitsdatum']     = due_date
                        row['rechnungsgesamtbetrag'] = total
                        row['trackingnummer']        = tracking
                        row['referenz']              = referenz
                        row['sendungsdatum']         = ship_date
                        row['serviceart']            = service or rechnungsart
                        row['cost_label']            = label
                        row['incoterm']              = ''
                        row['versender_name']        = sender_name
                        row['versender_land']        = sender_land
                        row['empfaenger_name']       = recv_name
                        row['empfaenger_land']       = recv_land
                        row['warenbeschreibung']     = goods_desc
                        row['gewicht_kg']            = weight
                        row['anzahl_pakete']         = pieces
                        row['verpackungsart']        = packaging
                        row['betrag_netto_eur']      = amount
                        row['betrag_brutto_eur']     = amount

                        rows.append(row)

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f'FedEx CSV parse error: {e}')

        return rows
