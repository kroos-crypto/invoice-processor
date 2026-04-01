"""Base parser class – all carrier parsers inherit from this."""
from datetime import datetime
import os


COLUMNS = [
    'eingang_datum',
    'dienstleister',
    'rechnungsnr',
    'rechnungsdatum',
    'faelligkeitsdatum',
    'rechnungsgesamtbetrag',
    'referenz',
    'trackingnummer',
    'sendungsdatum',
    'zustelldatum',
    'serviceart',
    'incoterm',
    'versender_name',
    'versender_land',
    'empfaenger_name',
    'empfaenger_land',
    'warenbeschreibung',
    'gewicht_kg',
    'anzahl_pakete',
    'verpackungsart',
    'betrag_netto_eur',
    'mwst_satz',
    'mwst_betrag_eur',
    'betrag_brutto_eur',
    'quelldatei',
]

# Human-readable German headers for Google Sheet
COLUMN_HEADERS = {
    'eingang_datum':           'Eingang-Datum',
    'dienstleister':           'Dienstleister',
    'rechnungsnr':             'Rechnungs-Nr.',
    'rechnungsdatum':          'Rechnungsdatum',
    'faelligkeitsdatum':       'Fälligkeitsdatum',
    'rechnungsgesamtbetrag':   'Rechnungsgesamtbetrag (EUR)',
    'referenz':                'Referenz (OR/BL/PBL)',
    'trackingnummer':          'Trackingnummer / Frachtbrief-Nr.',
    'sendungsdatum':           'Sendungsdatum',
    'zustelldatum':            'Zustelldatum',
    'serviceart':              'Serviceart',
    'incoterm':                'Incoterm',
    'versender_name':          'Versender Name',
    'versender_land':          'Versender Land',
    'empfaenger_name':         'Empfänger Name',
    'empfaenger_land':         'Empfänger Land',
    'warenbeschreibung':       'Warenbeschreibung',
    'gewicht_kg':              'Gewicht (kg)',
    'anzahl_pakete':           'Anzahl Pakete',
    'verpackungsart':          'Verpackungsart',
    'betrag_netto_eur':        'Betrag Netto (EUR)',
    'mwst_satz':               'MwSt-Satz (%)',
    'mwst_betrag_eur':         'MwSt-Betrag (EUR)',
    'betrag_brutto_eur':       'Betrag Brutto (EUR)',
    'quelldatei':              'Quelldatei',
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
            'eingang_datum': datetime.now().strftime('%d.%m.%Y %H:%M'),
            'quelldatei': os.path.basename(filepath) if filepath else '',
        }

    def rows_to_list(self, rows: list) -> list:
        """Convert list of dicts to list of lists (for Google Sheets)."""
        return [[row.get(col, '') for col in COLUMNS] for row in rows]
