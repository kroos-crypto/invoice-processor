"""
Google Sheets writer.
- Appends parsed invoice rows to the correct tab based on auto-categorization.
- Reads categorization rules from the 'Kategorieregeln' tab.
- Unknown cost labels go to the 'Ungeklaert' tab.
"""
import os
import json
import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from parsers.base import COLUMNS, COLUMN_HEADERS

logger = logging.getLogger(__name__)

# ─── Scopes ───────────────────────────────────────────────────────────────────
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.readonly',
]

# ─── Tab names ────────────────────────────────────────────────────────────────
TAB_TRANSPORT  = 'Transport'
TAB_ZOLL       = 'Zoll'
TAB_LAGER      = 'Lagerkosten & Diverse'
TAB_RULES      = 'Kategorieregeln'
TAB_UNKNOWN    = 'Ungeklaert'

MAIN_TABS = [TAB_TRANSPORT, TAB_ZOLL, TAB_LAGER]
ALL_TABS  = MAIN_TABS + [TAB_RULES, TAB_UNKNOWN]

VALID_CATEGORIES = {TAB_TRANSPORT, TAB_ZOLL, TAB_LAGER}
TAB_SKIP = '__SKIP__'   # special: rows with this category are silently dropped

# ─── Starter rules ────────────────────────────────────────────────────────────
STARTER_RULES = [
    # UPS charge descriptions (cost_label = col45 description, cp1252 encoding)
    # Zoll-relevante Beschreibungen
    ('UPS', 'Zoll',                         TAB_ZOLL),
    ('UPS', 'Vorlageprovisionsgeb.',         TAB_ZOLL),
    ('UPS', 'Vorlageprovisionsgebühr',       TAB_ZOLL),
    ('UPS', 'Zusätl. Tarifpos. Gebühr',     TAB_ZOLL),
    ('UPS', 'Zusätzl. Tarifpos. Gebühr',    TAB_ZOLL),
    ('UPS', 'Importgebühren',               TAB_ZOLL),
    ('UPS', 'Importgebuehren',              TAB_ZOLL),
    ('UPS', 'PGA-Ausschlussgebühr',         TAB_ZOLL),
    ('UPS', 'Other Govt Fees',              TAB_ZOLL),
    ('UPS', 'Gebühr Zölle und Steuern',     TAB_ZOLL),
    ('UPS', 'Lacey Act',                    TAB_ZOLL),
    # MwSt/Tax → überspringen (wird bereits im Parser gefiltert, aber als Fallback)
    ('FedEx', 'USt. CBS DE 19.%', TAB_SKIP),  # FedEx MwSt (Zoll-Rechnungen)
    ('FedEx', 'DE USt. 19.%',     TAB_SKIP),  # FedEx MwSt (Transport-Rechnungen)
    # UPS wildcard – alles andere → Transport
    ('UPS', '*',    TAB_TRANSPORT),
    # FedEx CSV charge labels
    ('FedEx', 'Zölle',                TAB_ZOLL),
    ('FedEx', 'Aufwendungspauschale', TAB_ZOLL),
    ('FedEx', 'Kraftstoffzuschlag',   TAB_TRANSPORT),
    ('FedEx', 'Transportgebühr',      TAB_TRANSPORT),
    ('FedEx', 'Express Fracht',       TAB_TRANSPORT),
    ('FedEx', 'Fracht',               TAB_TRANSPORT),
    ('FedEx', 'Residential Delivery', TAB_TRANSPORT),
    ('FedEx', 'Zustellgebühr',        TAB_TRANSPORT),
    # FedEx wildcard – any label not explicitly listed above → Transport
    # (Zölle + Aufwendungspauschale still match first and go to Zoll)
    ('FedEx', '*',                    TAB_TRANSPORT),
    # Transdirekt – everything is Transport
    ('Transdirekt', 'Frachtkosten',   TAB_TRANSPORT),
    ('Transdirekt', 'Loseverladung',  TAB_TRANSPORT),
    ('Transdirekt', '*',              TAB_TRANSPORT),
    # Raben – everything is Transport
    ('Raben',        '*',             TAB_TRANSPORT),
    # Expeditors – everything is Transport (user confirmed)
    ('Expeditors',   '*',             TAB_TRANSPORT),
    # Logfret – Air Freight = Transport
    ('Logfret',      'Air Freight',   TAB_TRANSPORT),
    ('Logfret',      '*',             TAB_TRANSPORT),
]

# ─── Client cache ─────────────────────────────────────────────────────────────
_client      = None
_spreadsheet = None
_rules_cache = None   # (timestamp, rules_dict)
RULES_TTL    = 300    # seconds before re-reading rules from sheet


def _get_client(credentials_path: str):
    global _client
    if _client is None:
        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        if creds_json:
            info  = json.loads(creds_json)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def _get_spreadsheet(credentials_path: str, spreadsheet_id: str):
    global _spreadsheet
    if _spreadsheet is None:
        client       = _get_client(credentials_path)
        _spreadsheet = client.open_by_key(spreadsheet_id)
    return _spreadsheet


def _get_or_create_ws(ss, title: str, rows: int = 2000, cols: int = 30):
    titles = [ws.title for ws in ss.worksheets()]
    if title not in titles:
        return ss.add_worksheet(title=title, rows=rows, cols=cols)
    return ss.worksheet(title)


# ─── Column format definitions ────────────────────────────────────────────────
# Columns that should display as DD.MM.YYYY date
DATE_COLUMNS = {'rechnungsdatum', 'faelligkeitsdatum', 'sendungsdatum', 'zustelldatum'}
# Columns that should display as German number  1.234,56
EUR_COLUMNS  = {'rechnungsgesamtbetrag', 'betrag_netto_eur', 'mwst_betrag_eur', 'betrag_brutto_eur'}


def _apply_column_formats(ws, total_rows: int = 5000):
    """Apply date and number formats to data columns (rows 2 onward)."""
    col_list = list(COLUMNS)
    for i, col in enumerate(col_list):
        letter = _col_letter(i + 1)
        data_range = f'{letter}2:{letter}{total_rows}'
        if col in DATE_COLUMNS:
            ws.format(data_range, {'numberFormat': {'type': 'DATE', 'pattern': 'DD.MM.YYYY'}})
        elif col in EUR_COLUMNS:
            ws.format(data_range, {'numberFormat': {'type': 'NUMBER', 'pattern': '#,##0.00'}})


# ─── Header initialisation ────────────────────────────────────────────────────
def ensure_headers(credentials_path: str, spreadsheet_id: str):
    ss      = _get_spreadsheet(credentials_path, spreadsheet_id)
    headers = [COLUMN_HEADERS[col] for col in COLUMNS]

    # Main data tabs
    for tab_name in MAIN_TABS:
        ws        = _get_or_create_ws(ss, tab_name, rows=5000, cols=len(headers) + 2)
        first_row = ws.row_values(1)
        # Rebuild headers if: tab is empty, first header is wrong, OR column count changed
        needs_header = (
            not first_row or
            first_row[0] != headers[0] or
            len(first_row) != len(headers)
        )
        if needs_header:
            ws.clear()           # wipe old data so mismatched rows don't remain
            ws.update('A1', [headers])
            ws.format(f'A1:{_col_letter(len(headers))}1', {
                'textFormat':      {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                'backgroundColor': {'red': 0.18, 'green': 0.34, 'blue': 0.56},
            })
            ws.freeze(rows=1)
            _apply_column_formats(ws, total_rows=5000)   # only format after fresh header

    # Kategorieregeln tab
    rules_ws  = _get_or_create_ws(ss, TAB_RULES, rows=500, cols=3)
    first_row = rules_ws.row_values(1)
    if not first_row or first_row[0] != 'Carrier':
        rules_ws.update('A1', [['Carrier', 'Cost_Label', 'Category']])
        rules_ws.format('A1:C1', {
            'textFormat':      {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'backgroundColor': {'red': 0.2, 'green': 0.5, 'blue': 0.3},
        })
        rules_ws.freeze(rows=1)
        # Insert starter rules
        rules_ws.append_rows(
            [[c, l, cat] for c, l, cat in STARTER_RULES],
            value_input_option='USER_ENTERED'
        )
        logger.info(f'Kategorieregeln tab initialised with {len(STARTER_RULES)} starter rules.')

    # Ungeklaert tab – same columns as main tabs so rows can be copied directly
    unk_headers = [COLUMN_HEADERS[col] for col in COLUMNS]
    unk_ws    = _get_or_create_ws(ss, TAB_UNKNOWN, rows=500, cols=len(unk_headers))
    first_row = unk_ws.row_values(1)
    needs_unk_header = (
        not first_row or
        first_row[0] != unk_headers[0] or
        len(first_row) != len(unk_headers)
    )
    if needs_unk_header:
        unk_ws.clear()
        unk_ws.update('A1', [unk_headers])
        unk_ws.format(f'A1:{_col_letter(len(unk_headers))}1', {
            'textFormat':      {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'backgroundColor': {'red': 0.7, 'green': 0.3, 'blue': 0.1},
        })
        unk_ws.freeze(rows=1)
        _apply_column_formats(unk_ws, total_rows=500)


# ─── Rules engine ─────────────────────────────────────────────────────────────
def load_rules(credentials_path: str, spreadsheet_id: str) -> dict:
    """
    Load categorization rules from the Kategorieregeln tab.
    Returns dict: {(carrier_lower, label_lower): category}
    Uses a short TTL cache to avoid re-reading on every upload.
    """
    global _rules_cache
    now = datetime.now().timestamp()

    if _rules_cache:
        ts, rules = _rules_cache
        if now - ts < RULES_TTL:
            return rules

    try:
        ss    = _get_spreadsheet(credentials_path, spreadsheet_id)
        ws    = ss.worksheet(TAB_RULES)
        data  = ws.get_all_values()
        rules = {}
        for row in data[1:]:  # skip header
            if len(row) < 3:
                continue
            carrier  = row[0].strip()
            label    = row[1].strip()
            category = row[2].strip()
            if carrier and label and category in VALID_CATEGORIES:
                rules[(carrier.lower(), label.lower())] = category

        _rules_cache = (now, rules)
        logger.info(f'Loaded {len(rules)} categorization rules from sheet.')
        return rules

    except Exception as e:
        logger.warning(f'Could not load rules from sheet: {e} – using starter rules.')
        rules = {}
        for carrier, label, category in STARTER_RULES:
            rules[(carrier.lower(), label.lower())] = category
        return rules


def categorize_row(row: dict, rules: dict) -> str:
    """
    Determine which tab a row belongs to.
    Priority:
      1. Exact match (carrier, cost_label)
      2. Wildcard (carrier, *)
      3. Wildcard (*, cost_label)
      4. TAB_UNKNOWN
    """
    carrier = (row.get('dienstleister') or '').lower()
    label   = (row.get('cost_label') or '').lower()

    # 1. Exact match
    cat = rules.get((carrier, label))
    if cat:
        return cat

    # 2. Carrier wildcard (carrier, *)
    cat = rules.get((carrier, '*'))
    if cat:
        return cat

    # 3. Global wildcard (*, cost_label)
    cat = rules.get(('*', label))
    if cat:
        return cat

    return TAB_UNKNOWN


# ─── Append rows ──────────────────────────────────────────────────────────────
def append_rows(rows: list[dict], category_override: str | None,
                credentials_path: str, spreadsheet_id: str) -> dict:
    """
    Auto-categorize and append rows to the correct tabs.
    category_override: if set (e.g. 'Lagerkosten & Diverse'), all rows go there.
    Returns dict with counts per tab.
    """
    if not rows:
        return {}

    rules   = load_rules(credentials_path, spreadsheet_id)
    ss      = _get_spreadsheet(credentials_path, spreadsheet_id)
    # Bucket rows by target tab
    buckets: dict[str, list] = {t: [] for t in ALL_TABS}

    for row in rows:
        if category_override and category_override in VALID_CATEGORIES:
            target = category_override
        else:
            target = categorize_row(row, rules)

        if target == TAB_SKIP:
            continue   # MwSt/Tax-Zeilen komplett ignorieren

        buckets[target].append(row)

    counts = {}

    # Write main tabs
    for tab_name in MAIN_TABS:
        tab_rows = buckets.get(tab_name, [])
        if tab_rows:
            ws   = ss.worksheet(tab_name)
            data = [[_cell(r.get(col, '')) for col in COLUMNS] for r in tab_rows]
            ws.append_rows(data, value_input_option='USER_ENTERED')
            counts[tab_name] = len(tab_rows)

    # Write Ungeklärt tab – same 26 columns as main tabs
    unk_rows = buckets.get(TAB_UNKNOWN, [])
    if unk_rows:
        ws   = ss.worksheet(TAB_UNKNOWN)
        data = [[_cell(r.get(col, '')) for col in COLUMNS] for r in unk_rows]
        ws.append_rows(data, value_input_option='USER_ENTERED')
        counts[TAB_UNKNOWN] = len(unk_rows)

    return counts


# ─── Duplicate check ──────────────────────────────────────────────────────────
def invoice_already_exists(invoice_nr: str, credentials_path: str,
                            spreadsheet_id: str) -> bool:
    if not invoice_nr:
        return False
    try:
        ss        = _get_spreadsheet(credentials_path, spreadsheet_id)
        col_idx   = list(COLUMNS).index('rechnungsnr') + 1
        for tab in MAIN_TABS:
            try:
                ws     = ss.worksheet(tab)
                values = ws.col_values(col_idx)
                if invoice_nr in values:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _cell(value):
    """Return a Sheets-compatible cell value.
    Floats are returned as-is so USER_ENTERED treats them as numbers
    and column number/date formats apply correctly.
    """
    if value is None:
        return ''
    if isinstance(value, float):
        return value   # let Sheets handle formatting via column format
    return str(value)


def _col_letter(n: int) -> str:
    """Convert column number (1-based) to letter (A, B, … Z, AA, …)"""
    result = ''
    while n:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result
