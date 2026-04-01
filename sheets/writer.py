"""
Google Sheets writer.
Appends parsed invoice rows to the correct tab based on category.
"""
import os
import json
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from parsers.base import COLUMNS, COLUMN_HEADERS

# ─── Configuration ────────────────────────────────────────────────────────────
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.readonly',
]

# Tab names in the Google Sheet
TAB_MAP = {
    'Transport':              'Transport',
    'Zoll':                   'Zoll',
    'Lagerkosten & Diverse':  'Lagerkosten & Diverse',
}

# ─── Module-level client cache ─────────────────────────────────────────────────
_client = None
_spreadsheet = None


def _get_client(credentials_path: str):
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def _get_spreadsheet(credentials_path: str, spreadsheet_id: str):
    global _spreadsheet
    if _spreadsheet is None:
        client = _get_client(credentials_path)
        _spreadsheet = client.open_by_key(spreadsheet_id)
    return _spreadsheet


# ─── Header initialisation ─────────────────────────────────────────────────────
def ensure_headers(credentials_path: str, spreadsheet_id: str):
    """
    Make sure all 3 tabs exist and have the correct header row.
    Call this once on app startup.
    """
    ss = _get_spreadsheet(credentials_path, spreadsheet_id)
    headers = [COLUMN_HEADERS[col] for col in COLUMNS]

    existing_titles = [ws.title for ws in ss.worksheets()]

    for tab_name in TAB_MAP.values():
        if tab_name not in existing_titles:
            ws = ss.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
        else:
            ws = ss.worksheet(tab_name)

        # Check if header row is already set
        first_row = ws.row_values(1)
        if not first_row or first_row[0] != headers[0]:
            ws.update('A1', [headers])
            # Format header row: bold + freeze
            ws.format('A1:Y1', {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.18, 'green': 0.34, 'blue': 0.56},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            })
            ws.freeze(rows=1)


# ─── Append rows ───────────────────────────────────────────────────────────────
def append_rows(rows: list[dict], category: str,
                credentials_path: str, spreadsheet_id: str) -> int:
    """
    Append a list of row dicts to the correct tab.
    Returns the number of rows written.
    """
    if not rows:
        return 0

    tab_name = TAB_MAP.get(category)
    if not tab_name:
        raise ValueError(f"Unbekannte Kategorie: {category!r}. "
                         f"Erlaubt: {list(TAB_MAP.keys())}")

    ss = _get_spreadsheet(credentials_path, spreadsheet_id)
    ws = ss.worksheet(tab_name)

    # Convert dicts → ordered lists matching COLUMNS
    today = datetime.today().strftime('%d.%m.%Y')
    data = []
    for row in rows:
        # Auto-fill eingang_datum if not set
        if not row.get('eingang_datum'):
            row['eingang_datum'] = today
        data.append([_cell(row.get(col, '')) for col in COLUMNS])

    ws.append_rows(data, value_input_option='USER_ENTERED')
    return len(data)


def _cell(value) -> str:
    """Convert a value to a Google Sheets-safe string."""
    if value is None:
        return ''
    if isinstance(value, float):
        # German decimal comma for Sheets
        return str(value).replace('.', ',')
    return str(value)


# ─── Duplicate check ───────────────────────────────────────────────────────────
def invoice_already_exists(invoice_nr: str, category: str,
                            credentials_path: str, spreadsheet_id: str) -> bool:
    """
    Check if invoice_nr already appears in the rechnungsnr column of the tab.
    Falls back to False on any error (allow upload, don't block on API issues).
    """
    if not invoice_nr:
        return False
    try:
        tab_name = TAB_MAP.get(category, list(TAB_MAP.values())[0])
        ss = _get_spreadsheet(credentials_path, spreadsheet_id)
        ws = ss.worksheet(tab_name)

        # Column index of rechnungsnr (0-based in COLUMNS, 1-based in Sheets)
        col_idx = COLUMNS.index('rechnungsnr') + 1
        values = ws.col_values(col_idx)
        return invoice_nr in values
    except Exception:
        return False
