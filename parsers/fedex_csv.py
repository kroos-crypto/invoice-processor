"""
FedEx CSV Invoice Parser.
Uses positional (index-based) reading because FedEx CSVs contain many
duplicate column names ("Luftfrachtbrief – Gebührenetikett" / "Gebührenbetrag"
repeated up to 50+ times). csv.DictReader would silently drop all but the last.

Fixed column positions (0-based, verified against real invoice export):
  0   Rechnungsland/-gebiet
  1   Rechnungsart
  3   Kundennummer für Rechnungsstellung
  5   FedEx Rechnungsnummer
  6   Rechnungsdatum
  7   Fälligkeitsdatum
  9   Gesamtbetrag Standardgebühren
 13   Fälliger ursprünglicher Betrag
 16   Luftfrachtbriefnummer (Master Tracking)
 18   Absenderreferenz 1
 19   Absenderreferenz 2
 20   Absenderreferenz 3
 21   Zustellnachweis – Datum
 24   Versanddatum (formatiert)
 29   Serviceverpackungsetikett  (e.g. "FedEx Int'l Economy Freight")
 32   Stücke
 33   Tatsächliches Gewicht
 38   Firma Absender
 43   Absenderadresse – Ort
 45   Absenderadresse – Postanschrift
 46   Absenderadresse Land/Gebiet
 47   Firma Empfänger
 52   Empfängeradresse – Ort
 54   Empfängeradresse – Postanschrift
 55   Empfängeradresse Land/Gebiet
 56   Sendungsverfolgungs-ID für MPS-Paket  (per-package, only on sub-rows)
 57   Abm. Länge
 58   Abm. Breite
 59   Abm. Höhe
 60   Abm. Divisor
 62   Wert berechnetes Gewicht
 63   Einheiten berechnetes Gewicht
 65   Luftfrachtbrief – Gesamtbetrag  (per-shipment subtotal)
 66+  Alternating Gebührenetikett / Gebührenbetrag pairs

Row structure within each shipment block:
  Master row  – contains service label, references, stücke, charges (idx 66+)
  Sub-rows    – one per package; contain MPS tracking + dimensions; no charges
"""
import csv
from pathlib import Path
from .base import BaseParser
from utils.normalizer import normalize_number, normalize_date

# ── Fixed column indices ──────────────────────────────────────────────────────
C_KUNDENNR          = 3
C_RECHNUNGSART      = 1
C_INVOICE_NR        = 5
C_INV_DATE          = 6
C_DUE_DATE          = 7
C_TOTAL_STD         = 9
C_TOTAL_DUE         = 13
C_TRACKING          = 16
C_REF1              = 18
C_REF2              = 19
C_REF3              = 20
C_DELIVERY_DATE     = 21   # Zustellnachweis – Datum
C_SHIP_DATE         = 24
C_SERVICE_LABEL     = 29   # Serviceverpackungsetikett (human-readable service name)
C_PIECES            = 32
C_WEIGHT            = 33
C_SENDER_NAME       = 38
C_SENDER_ORT        = 43
C_SENDER_PLZ        = 45
C_SENDER_LAND       = 46
C_RECV_NAME         = 47
C_RECV_ORT          = 52
C_RECV_PLZ          = 54
C_RECV_LAND         = 55
C_MPS_TRACKING      = 56   # per-package MPS tracking ID (sub-rows only)
C_DIM_LAENGE        = 57
C_DIM_BREITE        = 58
C_DIM_HOEHE         = 59
C_DIM_DIVISOR       = 60
C_WEIGHT_CALC       = 62   # Wert berechnetes Gewicht
C_WEIGHT_CALC_UNIT  = 63   # Einheiten berechnetes Gewicht
C_CHARGE_START      = 66   # first Gebührenetikett; +1 = Betrag, +2 = next Etikett …

# USt/VAT label fragments → skip these charge rows
UST_FRAGMENTS = ('USt.', 'Ust.', 'MwSt', 'VAT', 'Tax')


def _col(row: list, idx: int, default: str = '') -> str:
    try:
        return row[idx].strip()
    except (IndexError, AttributeError):
        return default


def _join_pkg(values: list) -> str:
    """Join non-empty package values with '; '."""
    cleaned = [str(v) for v in values if v not in ('', None)]
    if not cleaned:
        return ''
    if len(set(cleaned)) == 1:
        return cleaned[0]          # all same → single value
    return '; '.join(cleaned)


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

    # ── Main parse entry point ────────────────────────────────────────────────
    def parse_csv(self, filepath: str) -> list:
        rows = []
        try:
            with open(filepath, encoding='utf-8-sig', errors='replace', newline='') as f:
                reader = csv.reader(f)
                headers = next(reader)
                if len(headers) < C_CHARGE_START:
                    return []
                all_data = [r for r in reader if r]

            # ── Pass 1: group rows into shipment blocks ───────────────────────
            # Master row = has a service label (idx 29).
            # Sub-rows   = same tracking, have MPS tracking (idx 56), no charges.
            groups: list[dict] = []
            current: dict | None = None
            for data in all_data:
                tracking = _col(data, C_TRACKING)
                if not tracking:
                    continue
                service_label = _col(data, C_SERVICE_LABEL)
                mps = _col(data, C_MPS_TRACKING)
                if service_label or (current is None) or (tracking != current['tracking']):
                    # Start a new shipment block
                    if current is not None:
                        groups.append(current)
                    current = {'master': data, 'subs': [], 'tracking': tracking}
                elif mps:
                    # Sub-row: belongs to current shipment
                    current['subs'].append(data)
            if current is not None:
                groups.append(current)

            # ── Pass 2: generate charge rows per shipment block ───────────────
            for grp in groups:
                master = grp['master']
                subs   = grp['subs']
                rows.extend(self._process_group(master, subs, filepath))

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f'FedEx CSV parse error: {e}', exc_info=True)

        return rows

    # ── Process one shipment group ────────────────────────────────────────────
    def _process_group(self, master: list, subs: list, filepath: str) -> list:
        rows = []

        # ── Shipment-level fields (from master row) ───────────────────────────
        invoice_nr   = _col(master, C_INVOICE_NR)
        if not invoice_nr:
            return rows

        kundennr     = _col(master, C_KUNDENNR)
        inv_date     = normalize_date(_col(master, C_INV_DATE))
        due_date     = normalize_date(_col(master, C_DUE_DATE))
        total        = normalize_number(
                           _col(master, C_TOTAL_DUE) or _col(master, C_TOTAL_STD))
        tracking     = _col(master, C_TRACKING)
        ref1         = _col(master, C_REF1)
        ref2         = _col(master, C_REF2)
        ref3         = _col(master, C_REF3)
        delivery_dt  = normalize_date(_col(master, C_DELIVERY_DATE))
        ship_date    = normalize_date(_col(master, C_SHIP_DATE))
        service      = _col(master, C_SERVICE_LABEL)   # "FedEx Int'l Economy Freight"
        pieces       = _col(master, C_PIECES)
        weight       = normalize_number(_col(master, C_WEIGHT))
        weight_calc  = _col(master, C_WEIGHT_CALC)
        weight_unit  = _col(master, C_WEIGHT_CALC_UNIT)
        packaging    = ''
        sender_name  = _col(master, C_SENDER_NAME) or _col(master, 39)
        sender_plz   = _col(master, C_SENDER_PLZ)
        sender_ort   = _col(master, C_SENDER_ORT)
        sender_land  = _col(master, C_SENDER_LAND)
        recv_name    = _col(master, C_RECV_NAME) or _col(master, 48)
        recv_plz     = _col(master, C_RECV_PLZ)
        recv_ort     = _col(master, C_RECV_ORT)
        recv_land    = _col(master, C_RECV_LAND)

        # ── Aggregate package data from sub-rows ──────────────────────────────
        mps_ids     = [_col(s, C_MPS_TRACKING) for s in subs if _col(s, C_MPS_TRACKING)]
        laengen     = [_col(s, C_DIM_LAENGE)   for s in subs if _col(s, C_DIM_LAENGE)]
        breiten     = [_col(s, C_DIM_BREITE)   for s in subs if _col(s, C_DIM_BREITE)]
        hoehen      = [_col(s, C_DIM_HOEHE)    for s in subs if _col(s, C_DIM_HOEHE)]
        divisoren   = [_col(s, C_DIM_DIVISOR)  for s in subs if _col(s, C_DIM_DIVISOR)]

        mps_tracking = _join_pkg(mps_ids)
        abm_laenge   = _join_pkg(laengen)
        abm_breite   = _join_pkg(breiten)
        abm_hoehe    = _join_pkg(hoehen)
        abm_divisor  = _join_pkg(divisoren)

        # ── Walk charge pairs ─────────────────────────────────────────────────
        i = C_CHARGE_START
        while i + 1 < len(master):
            label  = _col(master, i)
            amount = normalize_number(_col(master, i + 1))
            i += 2

            if not label or not amount or amount == 0.0:
                continue

            # Skip USt / VAT charge rows
            if any(frag in label for frag in UST_FRAGMENTS):
                continue

            row = self.empty_row(filepath)
            row['dienstleister']         = 'FedEx'
            row['kundennummer']          = kundennr
            row['rechnungsnr']           = invoice_nr
            row['rechnungsdatum']        = inv_date
            row['faelligkeitsdatum']     = due_date
            row['rechnungsgesamtbetrag'] = total
            row['referenz_1']            = ref1
            row['referenz_2']            = ref2
            row['referenz_3']            = ref3
            row['trackingnummer']        = tracking
            row['sendungsdatum']         = ship_date
            row['zustelldatum']          = delivery_dt
            row['serviceart']            = service
            row['cost_label']            = label
            row['anzahl_pakete']         = pieces
            row['mps_tracking']          = mps_tracking
            row['abm_laenge']            = abm_laenge
            row['abm_breite']            = abm_breite
            row['abm_hoehe']             = abm_hoehe
            row['abm_divisor']           = abm_divisor
            row['gewicht_kg']            = weight
            row['gewicht_berechnet']     = weight_calc
            row['gewicht_einheit']       = weight_unit
            row['verpackungsart']        = packaging
            row['versender_name']        = sender_name
            row['versender_plz']         = sender_plz
            row['versender_ort']         = sender_ort
            row['versender_land']        = sender_land
            row['empfaenger_name']       = recv_name
            row['empfaenger_plz']        = recv_plz
            row['empfaenger_ort']        = recv_ort
            row['empfaenger_land']       = recv_land
            row['betrag_netto_eur']      = amount
            row['betrag_brutto_eur']     = amount

            rows.append(row)

        return rows
