"""
Invoice Processor – Flask Backend
Drag & drop upload → parse PDF/CSV/Excel → write to Google Sheets
"""
import os
import json
import logging
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, render_template, abort

from parsers import detect_and_parse
from sheets.writer import ensure_headers, append_rows, invoice_already_exists

# ─── Configuration ──────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
UPLOAD_DIR     = BASE_DIR / 'uploads'
PROCESSED_FILE = BASE_DIR / 'processed_invoices.json'

# Load from environment variables (set in .env or system)
CREDENTIALS_PATH  = os.environ.get('GOOGLE_CREDENTIALS', str(BASE_DIR / 'credentials.json'))
SPREADSHEET_ID    = os.environ.get('SPREADSHEET_ID', '')

ALLOWED_EXTENSIONS = {'.pdf', '.csv', '.xlsx', '.xls'}
MAX_FILE_SIZE_MB   = 50

CATEGORIES = ['Transport', 'Zoll', 'Lagerkosten & Diverse']

# ─── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE_MB * 1024 * 1024

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

UPLOAD_DIR.mkdir(exist_ok=True)


# ─── Duplicate tracking (local JSON, fast) ─────────────────────────────────────
def load_processed() -> dict:
    if PROCESSED_FILE.exists():
        try:
            return json.loads(PROCESSED_FILE.read_text())
        except Exception:
            pass
    return {}


def save_processed(data: dict):
    PROCESSED_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def mark_as_processed(invoice_nr: str, filename: str, category: str):
    data = load_processed()
    data[invoice_nr] = {
        'filename':  filename,
        'category':  category,
        'timestamp': datetime.now().isoformat(),
    }
    save_processed(data)


def is_duplicate(invoice_nr: str) -> dict | None:
    """Return existing entry if duplicate, else None."""
    if not invoice_nr:
        return None
    data = load_processed()
    return data.get(invoice_nr)


# ─── Startup ────────────────────────────────────────────────────────────────────
@app.before_request
def _once():
    """Ensure Google Sheet headers exist on first request (lazy init)."""
    if not SPREADSHEET_ID:
        return  # Skip if not configured yet
    try:
        ensure_headers(CREDENTIALS_PATH, SPREADSHEET_ID)
    except Exception as e:
        logger.warning(f'Could not initialise Google Sheet headers: {e}')


# ─── Routes ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', categories=CATEGORIES)


@app.route('/upload', methods=['POST'])
def upload():
    """
    Accepts: multipart/form-data with fields:
      - files[]:  one or more invoice files
      - category: one of CATEGORIES
      - referenz:  optional manual reference (OR.../BL.../PBL...)
      - force:    'true' to bypass duplicate check
    Returns: JSON { results: [...], errors: [...] }
    """
    category  = request.form.get('category', '').strip()
    referenz  = request.form.get('referenz', '').strip()
    force     = request.form.get('force', 'false').lower() == 'true'
    files     = request.files.getlist('files[]')

    # Validate category
    if category not in CATEGORIES:
        return jsonify({'error': f'Ungültige Kategorie: {category!r}. '
                                 f'Bitte wähle: {", ".join(CATEGORIES)}'}), 400

    if not files:
        return jsonify({'error': 'Keine Dateien hochgeladen.'}), 400

    results = []
    errors  = []

    for f in files:
        filename = f.filename or 'unknown'
        ext      = Path(filename).suffix.lower()

        if ext not in ALLOWED_EXTENSIONS:
            errors.append({'file': filename,
                           'error': f'Nicht unterstütztes Format: {ext}'})
            continue

        # Save to temp directory
        save_path = UPLOAD_DIR / filename
        try:
            f.save(str(save_path))
        except Exception as e:
            errors.append({'file': filename, 'error': f'Speicherfehler: {e}'})
            continue

        try:
            # Parse
            rows, invoice_nr, provider = detect_and_parse(str(save_path))

            # Duplicate check
            if invoice_nr and not force:
                existing = is_duplicate(invoice_nr)
                if existing:
                    results.append({
                        'file':       filename,
                        'status':     'duplicate',
                        'invoice_nr': invoice_nr,
                        'provider':   provider,
                        'message':    (f'Rechnung {invoice_nr} wurde bereits am '
                                       f'{existing["timestamp"][:10]} importiert '
                                       f'({existing["filename"]}).'),
                    })
                    continue

            # Apply manual reference if provided and row has none
            if referenz:
                for row in rows:
                    if not row.get('referenz'):
                        row['referenz'] = referenz

            # Write to Google Sheet
            written = 0
            sheet_error = None
            if SPREADSHEET_ID:
                try:
                    written = append_rows(rows, category, CREDENTIALS_PATH, SPREADSHEET_ID)
                except Exception as e:
                    sheet_error = str(e)
                    logger.error(f'Sheets write error for {filename}: {e}')
            else:
                sheet_error = 'SPREADSHEET_ID nicht konfiguriert'

            # Mark as processed (even if sheet failed, to avoid re-uploads)
            if invoice_nr and not sheet_error:
                mark_as_processed(invoice_nr, filename, category)

            results.append({
                'file':        filename,
                'status':      'ok' if not sheet_error else 'sheet_error',
                'invoice_nr':  invoice_nr,
                'provider':    provider,
                'category':    category,
                'rows_parsed': len(rows),
                'rows_written': written,
                'error':       sheet_error,
                'preview':     _make_preview(rows),
            })

        except Exception as e:
            logger.exception(f'Parse error for {filename}')
            errors.append({'file': filename, 'error': f'Parse-Fehler: {e}'})

        finally:
            # Clean up temp file
            try:
                save_path.unlink(missing_ok=True)
            except Exception:
                pass

    return jsonify({'results': results, 'errors': errors})


@app.route('/status')
def status():
    """Return current configuration status."""
    return jsonify({
        'spreadsheet_configured': bool(SPREADSHEET_ID),
        'credentials_exist':      Path(CREDENTIALS_PATH).exists(),
        'processed_invoices':     len(load_processed()),
    })


@app.route('/processed')
def processed():
    """Return list of all processed invoices."""
    return jsonify(load_processed())


# ─── Helper ─────────────────────────────────────────────────────────────────────
def _make_preview(rows: list) -> list:
    """Return a compact preview of rows for the UI (max 5 rows, key fields only)."""
    preview_fields = [
        'dienstleister', 'rechnungsnr', 'rechnungsdatum',
        'referenz', 'trackingnummer', 'betrag_brutto_eur', 'serviceart',
    ]
    return [
        {k: r.get(k, '') for k in preview_fields}
        for r in rows[:5]
    ]


# ─── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
