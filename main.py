import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO

import pandas as pd
from js import Blob, URL, Uint8Array, document
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError
from pyscript import when


dataframe = None
holdings_by_period = {"opening": {}, "closing": {}}
january_included_rows = set()
JANUARY_REVIEW_CUTOFF = 13
isin_pattern = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b")
number_pattern = re.compile(r"^[+-]?\d[\d'’.,]*$")
fiat_currencies = {
    "AED", "AUD", "CAD", "CHF", "CNY", "DKK", "EUR", "GBP", "HKD",
    "JPY", "NOK", "NZD", "SEK", "SGD", "USD",
}
non_asset_labels = {
    "ABSOLUTE", "CUSTOMER", "PERFORMANCE", "SWISSQUOTE", "TOTAL",
}
income_transaction_types = {
    "dividende": "Dividende",
    "zinsen auf einlagen": "Zinsen auf Einlagen",
    "wertpapierleihe": "Wertpapierleihe",
    "zinsen auf belastungen": "Zinsen auf Belastungen (Aufwand)",
}


def set_status(selector, message, is_error=False):
    status = document.querySelector(selector)
    status.textContent = message
    status.dataset.error = "true" if is_error else "false"


def parse_number(value):
    normalized = value.strip().replace("’", "").replace("'", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        decimal_separator = "," if normalized.rfind(",") > normalized.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        normalized = normalized.replace(thousands_separator, "").replace(
            decimal_separator, "."
        )
    else:
        normalized = normalized.replace(",", ".")
    try:
        result = Decimal(normalized)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def csv_symbols_by_isin():
    if dataframe is None:
        return {}

    columns = {str(column).strip().casefold(): column for column in dataframe.columns}
    isin_column = columns.get("isin")
    symbol_column = columns.get("symbol")
    if isin_column is None or symbol_column is None:
        return {}

    symbols = {}
    for _, row in dataframe[[isin_column, symbol_column]].dropna().iterrows():
        isin = str(row[isin_column]).strip().upper()
        symbol = str(row[symbol_column]).strip()
        if isin and symbol:
            symbols[isin] = symbol
    return symbols


def display_symbol(position):
    return csv_symbols_by_isin().get(position["ISIN"]) or position[
        "Ticker / Wertpapier / Währung"
    ]


def format_number(value):
    formatted = format(value, "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def parse_transaction_date(value):
    if pd.isna(value):
        return None

    date_text = str(value).strip()
    iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", date_text)
    if iso_match is None:
        iso_match = re.search(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b", date_text)
    if iso_match:
        try:
            return datetime(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
            ).date()
        except ValueError:
            return None

    swiss_match = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b", date_text)
    if swiss_match:
        day, month, year = (int(part) for part in swiss_match.groups())
        if year < 100:
            year += 2000 if year < 70 else 1900
        try:
            return datetime(year, month, day).date()
        except ValueError:
            return None

    for date_format in (
        "%d.%m.%Y",
        "%d.%m.%y",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(date_text, date_format).date()
        except ValueError:
            continue
    return None


def categorize_income_transaction(value):
    normalized = " ".join(str(value).casefold().split())
    exact_category = income_transaction_types.get(normalized)
    if exact_category:
        return exact_category
    if "dividend" in normalized:
        return "Dividende"
    if "zins" in normalized and "einlag" in normalized:
        return "Zinsen auf Einlagen"
    if "zins" in normalized and ("belast" in normalized or "soll" in normalized):
        return "Zinsen auf Belastungen (Aufwand)"
    if "wertpapierleihe" in normalized or "securities lending" in normalized:
        return "Wertpapierleihe"
    return None


def parse_holdings_pdf(file_bytes):
    reader = PdfReader(BytesIO(file_bytes))
    text = "\n".join(
        page.extract_text(extraction_mode="layout") or "" for page in reader.pages
    )
    if not text.strip():
        raise ValueError(
            "Im PDF wurde kein auswählbarer Text gefunden. "
            "Möglicherweise ist es ein Scan; OCR wird noch nicht unterstützt."
        )

    parsed = {}
    symbols = csv_symbols_by_isin()
    current_section = "Aktie"
    pending_currency_section = None
    in_currency_table = False

    for line in text.splitlines():
        normalized_line = " ".join(line.casefold().split())
        if re.search(r"\b(liquidität|liquiditaet|cash|konten?)\b", normalized_line):
            current_section = "Liquidität"
            pending_currency_section = "Liquidität"
            in_currency_table = False
            continue
        if re.search(
            r"\b(krypto\w*|kryptowaehrung\w*|crypto\w*)\b",
            normalized_line,
        ):
            current_section = "Kryptowährung"
            pending_currency_section = "Kryptowährung"
            in_currency_table = False
            continue
        if re.search(r"\b(anlagefonds|investmentfonds|fonds)\b", normalized_line):
            current_section = "Anlagefonds"
            pending_currency_section = None
            in_currency_table = False
            continue
        if re.search(r"\b(aktien|aktienbestand|wertpapiere)\b", normalized_line):
            current_section = "Aktie"
            pending_currency_section = None
            in_currency_table = False
            continue
        if (
            pending_currency_section
            and "währung" in normalized_line
            and "beschreibung" in normalized_line
            and "wechselkurs" in normalized_line
        ):
            in_currency_table = True
            current_section = pending_currency_section
            pending_currency_section = None
            continue
        if "anzahl" in normalized_line and "isin" in normalized_line:
            in_currency_table = False
            continue

        isin_match = isin_pattern.search(line.upper())
        if isin_match:
            before_isin = line[:isin_match.start()].split()
            if not before_isin:
                continue
            quantity = parse_number(before_isin[0])
            if quantity is None:
                continue

            isin = isin_match.group(0).upper()
            name = " ".join(before_isin[1:]).strip()
            asset_type = (
                "Anlagefonds" if current_section == "Anlagefonds" else "Aktie"
            )
            key = (asset_type, isin)
            parsed[key] = {
                "Art": asset_type,
                "Ticker / Wertpapier / Währung": symbols.get(isin) or name,
                "ISIN": isin,
                "Stückzahl": quantity,
            }
            continue

        if not in_currency_table:
            continue

        columns = re.split(r"\s{2,}", line.strip())
        if len(columns) < 3:
            continue

        currency = columns[0].strip()
        if (
            not re.fullmatch(r"[A-Z][A-Z0-9._-]{1,11}", currency.upper())
            or (
                current_section == "Kryptowährung"
                and currency.upper() in fiat_currencies
            )
            or currency.upper() in non_asset_labels
        ):
            continue
        numeric_values = [
            parse_number(value.rstrip("%"))
            for value in columns[2:]
            if number_pattern.fullmatch(value.rstrip("%"))
        ]
        if len(numeric_values) < 3:
            continue
        quantity = numeric_values[0]
        if quantity is None:
            continue

        key = (current_section, currency.upper())
        parsed[key] = {
            "Art": current_section,
            "Ticker / Wertpapier / Währung": currency.upper(),
            "ISIN": "",
            "Stückzahl": quantity,
        }

    return parsed


def render_holdings():
    rows = {}
    for period in ("opening", "closing"):
        for key, position in holdings_by_period[period].items():
            row = rows.setdefault(
                key,
                {
                    "Art": position["Art"],
                    "Ticker / Wertpapier / Währung": display_symbol(position),
                    "ISIN": position["ISIN"],
                    "Bestand / Wert Anfang": "—",
                    "Bestand / Wert Ende": "—",
                    "Änderung": "—",
                },
            )
            row[
                "Bestand / Wert Anfang"
                if period == "opening"
                else "Bestand / Wert Ende"
            ] = (
                str(position["Stückzahl"])
            )

    for key, row in rows.items():
        opening = holdings_by_period["opening"].get(key)
        closing = holdings_by_period["closing"].get(key)
        if opening is not None and closing is not None:
            row["Änderung"] = format_number(
                closing["Stückzahl"] - opening["Stückzahl"]
            )

    body = document.querySelector("#holdings-body")
    body.replaceChildren()
    for position in rows.values():
        row = document.createElement("tr")
        for value in position.values():
            cell = document.createElement("td")
            cell.textContent = value
            row.appendChild(cell)
        body.appendChild(row)

    has_holdings = bool(rows)
    document.querySelector("#download-holdings").disabled = not has_holdings
    opening_count = len(holdings_by_period["opening"])
    closing_count = len(holdings_by_period["closing"])
    if has_holdings:
        set_status(
            "#holdings-status",
            f"Erkannte Positionen: Anfang {opening_count}, Ende {closing_count}. "
            "„—“ bedeutet: in diesem PDF nicht erkannt.",
        )
    elif opening_count == 0 and closing_count == 0:
        set_status("#holdings-status", "Bitte wähle die beiden Bestands-PDFs aus.")


async def load_holdings_pdf(event, period, period_label):
    selected_file = event.target.files.item(0)
    if selected_file is None:
        return

    holdings_by_period[period] = {}
    set_status("#holdings-status", f"Lese PDF für {period_label}: {selected_file.name} …")

    try:
        file_bytes = bytes(Uint8Array.new(await selected_file.arrayBuffer()))
        holdings_by_period[period] = parse_holdings_pdf(file_bytes)
    except (PdfReadError, FileNotDecryptedError, ValueError) as error:
        render_holdings()
        set_status(
            "#holdings-status",
            f"{selected_file.name} konnte nicht verarbeitet werden: {error}",
            True,
        )
        return

    render_holdings()
    count = len(holdings_by_period[period])
    if count == 0:
        set_status(
            "#holdings-status",
            f"Im PDF für {period_label} wurde Text gelesen, aber keine "
            "Bestandszeile erkannt. Das Tabellenlayout muss möglicherweise "
            "noch angepasst werden.",
            True,
        )


@when("change", "#opening-pdf")
async def load_opening_pdf(event):
    await load_holdings_pdf(event, "opening", "Anfang")


@when("change", "#closing-pdf")
async def load_closing_pdf(event):
    await load_holdings_pdf(event, "closing", "Ende")


@when("click", "#download-holdings")
def download_holdings(event):
    records = []
    for key in sorted(
        set(holdings_by_period["opening"]) | set(holdings_by_period["closing"])
    ):
        opening = holdings_by_period["opening"].get(key)
        closing = holdings_by_period["closing"].get(key)
        position = opening or closing
        records.append(
            {
                "Art": position["Art"],
                "Ticker / Wertpapier / Währung": display_symbol(position),
                "ISIN": position["ISIN"],
                "Bestand / Wert Anfang": opening["Stückzahl"] if opening else "",
                "Bestand / Wert Ende": closing["Stückzahl"] if closing else "",
                "Änderung": (
                    format_number(closing["Stückzahl"] - opening["Stückzahl"])
                    if opening and closing
                    else ""
                ),
            }
        )

    if not records:
        set_status("#holdings-status", "Es wurden noch keine Positionen erkannt.", True)
        return

    csv_content = "\ufeff" + pd.DataFrame(records).to_csv(index=False)
    download_file(csv_content, "bestandsuebersicht-2025.csv")


def render_income_report():
    totals_body = document.querySelector("#income-totals")
    transactions_body = document.querySelector("#income-transactions")
    january_body = document.querySelector("#january-review")
    totals_body.replaceChildren()
    transactions_body.replaceChildren()
    january_body.replaceChildren()

    if dataframe is None:
        set_status(
            "#income-status",
            "Lade die Transaktions-CSV, um Buchungen zu prüfen.",
        )
        return

    columns = {str(column).strip().casefold(): column for column in dataframe.columns}
    required_columns = ("datum", "transaktionen", "nettobetrag", "währung")
    missing_columns = [name for name in required_columns if name not in columns]
    if missing_columns:
        set_status(
            "#income-status",
            "Keine Ertragsauswertung möglich. In der CSV fehlen: "
            + ", ".join(missing_columns)
            + ".",
            True,
        )
        return

    totals = {}
    included_count = 0
    invalid_amount_count = 0
    invalid_date_count = 0
    january_count = 0
    selected_january_count = 0
    unsupported_january_count = 0
    unparsed_date_count = 0
    january_after_cutoff_count = 0
    date_column = columns.get("datum")
    symbol_column = columns.get("symbol")
    name_column = columns.get("name")

    for row_index, transaction in dataframe.iterrows():
        transaction_type = str(transaction[columns["transaktionen"]]).strip()
        transaction_date = parse_transaction_date(transaction[date_column])
        if transaction_date is None:
            unparsed_date_count += 1
            if categorize_income_transaction(transaction_type):
                invalid_date_count += 1
            continue

        category = categorize_income_transaction(transaction_type)
        is_tax_year_transaction = transaction_date.year == 2025
        is_january_2026 = transaction_date.year == 2026 and transaction_date.month == 1
        is_january_review = (
            is_january_2026 and transaction_date.day <= JANUARY_REVIEW_CUTOFF
        )
        if is_january_2026 and not is_january_review:
            january_after_cutoff_count += 1
        if is_january_review:
            january_count += 1
            if category is None:
                unsupported_january_count += 1

        if not is_tax_year_transaction and not is_january_review:
            continue
        if not is_january_review and category is None:
            continue

        currency_value = transaction[columns["währung"]]
        currency = (
            str(currency_value).strip()
            if pd.notna(currency_value) and str(currency_value).strip()
            else "—"
        )
        amount_value = transaction[columns["nettobetrag"]]
        amount_text = (
            str(amount_value).strip()
            if pd.notna(amount_value) and str(amount_value).strip()
            else ""
        )
        amount = parse_number(amount_text) if amount_text else None
        if amount is None:
            if category is not None:
                invalid_amount_count += 1
        elif category and (is_tax_year_transaction or row_index in january_included_rows):
            total_key = (category, currency)
            totals[total_key] = totals.get(total_key, Decimal(0)) + amount
            if is_january_review and row_index in january_included_rows:
                selected_january_count += 1

        cells = [
            transaction_date.isoformat(),
            transaction_type,
            category or "Nicht als Ertrag kategorisiert",
            transaction[symbol_column] if symbol_column is not None else "",
            transaction[name_column] if name_column is not None else "",
            amount_text,
            currency,
        ]
        row = document.createElement("tr")
        for value in cells:
            cell = document.createElement("td")
            cell.textContent = "" if pd.isna(value) else str(value)
            row.appendChild(cell)
        if is_january_review:
            checkbox_cell = document.createElement("td")
            checkbox = document.createElement("input")
            checkbox.type = "checkbox"
            checkbox.checked = category is not None and row_index in january_included_rows
            checkbox.disabled = category is None
            if category is not None:
                checkbox.dataset.rowIndex = str(row_index)
                checkbox.setAttribute(
                    "aria-label",
                    f"Buchung vom {transaction_date.isoformat()} für 2025 berücksichtigen",
                )
            checkbox_cell.appendChild(checkbox)
            row.insertBefore(checkbox_cell, row.firstChild)
            january_body.appendChild(row)
            if category is not None:
                included_count += 1
        elif category is not None:
            transactions_body.appendChild(row)
            included_count += 1

    for (category, currency), amount in sorted(totals.items()):
        row = document.createElement("tr")
        for value in (category, currency, format_number(amount)):
            cell = document.createElement("td")
            cell.textContent = value
            row.appendChild(cell)
        totals_body.appendChild(row)

    message = f"{included_count} als Ertrag kategorisierte Buchung(en) aus 2025 und Januar 2026 gefunden. "
    if january_count:
        message += (
            f"{january_count} Transaktion(en) vom 1.–{JANUARY_REVIEW_CUTOFF}. Januar "
            "werden separat angezeigt; "
            f"{selected_january_count} davon sind ausgewählt und in den Summen. "
        )
    else:
        message += (
            f"Keine Transaktionen vom 1.–{JANUARY_REVIEW_CUTOFF}. Januar 2026 "
            "gefunden. "
        )
    if january_after_cutoff_count:
        message += (
            f"{january_after_cutoff_count} weitere Januar-Transaktion(en) nach dem "
            f"{JANUARY_REVIEW_CUTOFF}. Januar sind nicht im Prüffenster. "
        )
    if unsupported_january_count:
        message += (
            f"{unsupported_january_count} Januar-Transaktion(en) sind nicht als "
            "Ertrag kategorisiert und deshalb nicht auswählbar. "
        )
    message += "Summen werden getrennt nach Buchungsart und Währung angezeigt."
    if invalid_date_count:
        message += (
            f" {invalid_date_count} passende Buchung(en) hatten ein nicht "
            "erkennbares Datum und wurden nicht zugeordnet."
        )
    if unparsed_date_count:
        message += (
            f" Bei insgesamt {unparsed_date_count} CSV-Zeile(n) konnte das "
            "Datum nicht gelesen werden; diese Zeilen lassen sich keinem "
            "Zeitraum zuordnen."
        )
    if invalid_amount_count:
        message += (
            f" Bei {invalid_amount_count} Buchung(en) war der Nettobetrag "
            "nicht als Zahl auswertbar; sie erscheinen nur in der Einzelliste."
        )
    set_status(
        "#income-status",
        message,
        bool(
            invalid_amount_count
            or invalid_date_count
            or unsupported_january_count
            or unparsed_date_count
        ),
    )


@when("change", "#january-review")
def update_january_inclusion(event):
    checkbox = event.target
    row_index = checkbox.dataset.rowIndex
    if row_index is None:
        return

    row_index = int(row_index)
    if checkbox.checked:
        january_included_rows.add(row_index)
    else:
        january_included_rows.discard(row_index)
    render_income_report()


@when("change", "#csv-file")
async def load_csv(event):
    global dataframe

    selected_file = event.target.files.item(0)
    if selected_file is None:
        return

    document.querySelector("#download-button").disabled = True
    january_included_rows.clear()
    set_status("#csv-status", f"Lese {selected_file.name} …")

    try:
        file_bytes = bytes(Uint8Array.new(await selected_file.arrayBuffer()))
        try:
            file_contents = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            file_contents = file_bytes.decode("cp1252")
        dataframe = pd.read_csv(StringIO(file_contents), sep=None, engine="python")
    except (pd.errors.ParserError, ValueError, UnicodeDecodeError) as error:
        dataframe = None
        document.querySelector("#result-table").textContent = (
            "Die Datei konnte nicht als CSV gelesen werden."
        )
        render_income_report()
        set_status("#csv-status", f"CSV konnte nicht gelesen werden: {error}", True)
        return

    preview = dataframe.head(5).to_html(
        index=False,
        escape=True,
        border=0,
        classes="preview-table",
    )
    document.querySelector("#result-table").innerHTML = preview
    document.querySelector("#download-button").disabled = False
    set_status(
        "#csv-status",
        f"{selected_file.name}: {len(dataframe)} Zeilen und "
        f"{len(dataframe.columns)} Spalten geladen. "
        f"Spalten: {', '.join(str(column) for column in dataframe.columns)}",
    )
    render_holdings()
    render_income_report()


@when("click", "#download-button")
def download_csv(event):
    if dataframe is None:
        set_status("#csv-status", "Bitte laden Sie zuerst eine CSV-Datei.", True)
        return

    csv_content = "\ufeff" + dataframe.to_csv(index=False)
    download_file(csv_content, "swissquote-transaktionen.csv")


def download_file(content, filename):
    csv_blob = Blob.new([content], {"type": "text/csv;charset=utf-8"})
    download_url = URL.createObjectURL(csv_blob)
    link = document.createElement("a")
    link.href = download_url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(download_url)
