from .fedex import FedExTransportParser, FedExZollParser
from .fedex_csv import FedExCSVParser
from .ups import UPSTransportParser, UPSZollParser, UPSAbholParser
from .ups_csv import UPSCSVParser
from .transdirekt import TransdirektParser
from .raben import RabenParser
from .expeditors import ExpEditorsParser
from .logfret import LogfretParser
from .generic import GenericParser

# CSV parsers must come first – they check the file extension and bail early,
# so they don't interfere with PDF parsing of same-carrier invoices.
PARSERS = [
    UPSCSVParser(),
    FedExCSVParser(),
    FedExZollParser(),
    FedExTransportParser(),
    UPSZollParser(),
    UPSAbholParser(),
    UPSTransportParser(),
    TransdirektParser(),
    RabenParser(),
    ExpEditorsParser(),
    LogfretParser(),
]

def detect_and_parse(filepath: str):
    """
    Detect carrier from file content and parse accordingly.
    Returns: (rows: list[dict], invoice_nr: str, provider: str)
    """
    import pdfplumber, os

    ext = os.path.splitext(filepath)[1].lower()
    full_text = ''

    if ext == '.pdf':
        try:
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    full_text += (page.extract_text() or '') + '\n'
        except Exception as e:
            full_text = ''

    # Try each parser
    for parser in PARSERS:
        if parser.detect(full_text, filepath):
            if ext == '.pdf':
                rows = parser.parse_pdf(filepath, full_text)
            elif ext in ('.xlsx', '.xls'):
                rows = parser.parse_excel(filepath)
            elif ext == '.csv':
                rows = parser.parse_csv(filepath)
            else:
                rows = []

            invoice_nr = rows[0].get('rechnungsnr', '') if rows else ''
            return rows, invoice_nr, parser.name

    # Fallback
    generic = GenericParser()
    rows = generic.parse_pdf(filepath, full_text) if ext == '.pdf' else []
    invoice_nr = rows[0].get('rechnungsnr', '') if rows else ''
    return rows, invoice_nr, 'Unbekannt'
