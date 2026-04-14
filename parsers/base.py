"""Base parser class – all carrier parsers inherit from this."""
import os


COLUMNS = [
    # ── Invoice header ─────────────────────────────────────────────
    'dienstleister',
    'kundennummer',
    'rechnungsnr',
    'rechnungsdatum',
    'faelligkeitsdatum',
    'rechnungsgesamtbetrag',
    # ── References (Absenderreferenz 1 / 2 / 3) ───────────────────
    'referenz_1',
    'referenz_2',
    'referenz_3',
    # ── Tracking & dates ──────────────────────────────────────────
    'trackingnummer',
    'sendungsdatum',
    'zustelldatum',
    # ── Service & charge ──────────────────────────────────────────
    'serviceart',
    'cost_label',
    'incoterm',
    # ── Shipment / package details ────────────────────────────────
    'anzahl_pakete',
    'mps_tracking',
    'abm_laenge',
    'abm_breite',
    'abm_hoehe',
    'abm_divisor',
    'gewicht_kg',
    'gewicht_berechnet',
    'gewicht_einheit',
    'verpackungsart',
    # ── Sender address ────────────────────────────────────────────
    'versender_name',
    'versender_plz',
    'versender_ort',
    'versender_land',
    # ── Receiver address ──────────────────────────────────────────
    'empfaenger_name',
    'empfaenger_plz',
    'empfaenger_ort',
    'empfaenger_land',
    # ── Goods ─────────────────────────────────────────────────────
    'warenbeschreibung',
    # ── Costs ─────────────────────────────────────────────────────
    'betrag_netto_eur',
    'mwst_satz',
    'mwst_betrag_eur',
    'betrag_brutto_eur',
    # ── Meta ──────────────────────────────────────────────────────
    'quelldatei',
]

# Human-readable German headers for Google Sheet
COLUMN_HEADERS = {
    'dienstleister':          'Dienstleister',
    'kundennummer':           'Kundennummer',
    'rechnungsnr':            'Rechnungs-Nr.',
    'rechnungsdatum':         'Rechnungsdatum',
    'faelligkeitsdatum':      'Fälligkeitsdatum',
    'rechnungsgesamtbetrag':  'Rechnungsgesamtbetrag (EUR)',
    'referenz_1':             'Absenderreferenz 1',
    'referenz_2':             'Absenderreferenz 2',
    'referenz_3':             'Absenderreferenz 3',
    'trackingnummer':         'Master Tracking',
    'sendungsdatum':          'Sendungsdatum',
    'zustelldatum':           'Zustelldatum',
    'serviceart':             'Service',
    'cost_label':             'Cost Label (Original)',
    'incoterm':               'Incoterm',
    'anzahl_pakete':          'Stücke',
    'mps_tracking':           'MPS Tracking-IDs',
    'abm_laenge':             'Abm. Länge (cm)',
    'abm_breite':             'Abm. Breite (cm)',
    'abm_hoehe':              'Abm. Höhe (cm)',
    'abm_divisor':            'Abm. Divisor',
    'gewicht_kg':             'Gewicht Ist (kg)',
    'gewicht_berechnet':      'Gewicht Berechnet',
    'gewicht_einheit':        'Gew.-Einheit',
    'verpackungsart':         'Verpackungsart',
    'versender_name':         'Versender Name',
    'versender_plz':          'Versender PLZ',
    'versender_ort':          'Versender Ort',
    'versender_land':         'Versender Land',
    'empfaenger_name':        'Empfänger Name',
    'empfaenger_plz':         'Empfänger PLZ',
    'empfaenger_ort':         'Empfänger Ort',
    'empfaenger_land':        'Empfänger Land',
    'warenbeschreibung':      'Warenbeschreibung',
    'betrag_netto_eur':       'Betrag Netto (EUR)',
    'mwst_satz':              'MwSt-Satz (%)',
    'mwst_betrag_eur':        'MwSt-Betrag (EUR)',
    'betrag_brutto_eur':      'Betrag Brutto (EUR)',
    'quelldatei':             'Quelldatei',
}


class BaseParser:
    name = 'Unbekannt'

    def detect(self, text: str, filepath: str = '') -> bool:
        """Return True if this parser can handle the document."""
        return False

    def parse_pdf(self, filepath: str, text: str = '') -> list:
        return []

    def parse_excel(self, filepath: str) -> list:
        return []

    def parse_csv(self, filepath: str) -> list:
        return []

    def empty_row(self, filepath: str = '') -> dict:
        return {col: '' for col in COLUMNS} | {
            'quelldatei': os.path.basename(filepath) if filepath else '',
        }

    def rows_to_list(self, rows: list) -> list:
        """Convert list of dicts to list of lists (for Google Sheets)."""
        return [[row.get(col, '') for col in COLUMNS] for row in rows]
