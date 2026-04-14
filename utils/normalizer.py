"""
Utility functions for normalizing numbers, dates, and text
across different carrier invoice formats.
"""
import re
from datetime import datetime


def normalize_number(value_str) -> float | None:
    """
    Convert various number formats to float.
    Handles:
      - English: 1,300.50  or  19,864.81
      - German:  1.300,50  or  19.864,81
      - Plain:   1300.50   or  1300,50
    """
    if value_str is None:
        return None
    s = str(value_str).strip()
    s = re.sub(r'[€$EURR\s]', '', s)
    s = s.replace('\xa0', '')

    if not s or s in ('-', '–'):
        return None

    # Handle negative in parentheses: (1.234,56)
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1]
    if s.startswith('-'):
        negative = True
        s = s[1:]

    # Both separators present
    if '.' in s and ',' in s:
        last_dot = s.rfind('.')
        last_comma = s.rfind(',')
        if last_dot > last_comma:
            # English: 1,300.50
            s = s.replace(',', '')
        else:
            # German: 1.300,50
            s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        # Could be German decimal (1300,50) or English thousands (1,300)
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = s.replace(',', '.')   # German decimal
        else:
            s = s.replace(',', '')    # English thousands

    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def normalize_date(date_str) -> str:
    """
    Convert various date formats to DD.MM.YYYY.
    Handles: 08/08/2025, 2025-08-08, 08.08.2025,
             18-Mrz-26, 25.Februar 2026, 04.Februar 2026
    """
    if not date_str:
        return ''
    s = str(date_str).strip()

    # German month names (full and abbreviated)
    DE_MONTHS = {
        'januar': '01', 'jan': '01',
        'februar': '02', 'feb': '02',
        'märz': '03', 'mrz': '03', 'mar': '03',
        'april': '04', 'apr': '04',
        'mai': '05',
        'juni': '06', 'jun': '06',
        'juli': '07', 'jul': '07',
        'august': '08', 'aug': '08',
        'september': '09', 'sep': '09',
        'oktober': '10', 'okt': '10', 'oct': '10',
        'november': '11', 'nov': '11',
        'dezember': '12', 'dez': '12', 'dec': '12',
    }

    # Try "25.Februar 2026" or "04.Februar 2026"
    m = re.match(r'(\d{1,2})\.\s*([A-Za-zä]+)\s+(\d{4})', s)
    if m:
        day, mon, year = m.group(1).zfill(2), m.group(2).lower(), m.group(3)
        if mon in DE_MONTHS:
            return f'{day}.{DE_MONTHS[mon]}.{year}'

    # Try "18-Mrz-26" or "01-Apr-26"
    m = re.match(r'(\d{1,2})-([A-Za-z]+)-(\d{2,4})', s)
    if m:
        day, mon, year = m.group(1).zfill(2), m.group(2).lower(), m.group(3)
        if len(year) == 2:
            year = '20' + year
        if mon in DE_MONTHS:
            return f'{day}.{DE_MONTHS[mon]}.{year}'

    # Standard strptime formats – note: Python's %d/%m accept 1- or 2-digit values
    for fmt in ('%d/%m/%Y', '%d.%m.%Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%y',
                '%m/%d/%y', '%Y%m%d'):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime('%d.%m.%Y')   # always zero-padded
        except ValueError:
            continue

    # Last-ditch: try to parse D.M.YYYY (single-digit day and/or month)
    m = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', s)
    if m:
        day, mon, year = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
        return f'{day}.{mon}.{year}'

    return s  # Return as-is


def format_number_german(value) -> str:
    """Format float as German number string: 1.234,56"""
    if value is None:
        return ''
    try:
        return f'{float(value):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return ''


def extract_country_from_address(address: str) -> str:
    """Try to extract country from last line of address block."""
    if not address:
        return ''
    lines = [l.strip() for l in address.strip().splitlines() if l.strip()]
    if lines:
        return lines[-1]
    return ''


def clean_text(text: str) -> str:
    """Remove excessive whitespace from text."""
    if not text:
        return ''
    return re.sub(r'\s+', ' ', text).strip()
