"""Reine Auswertungslogik ohne Browser- oder Dateiabhaengigkeiten.

Portiert die Power-Query-Abfragen der Mappe PQ_Swissquote_Steuerauszug:

    transaktionen            -> lies_transaktionen
    tbl_regeln               -> standard_regeln / lies_regeln
    Uebersicht_Anfangsb/Endb -> lies_bestand
    Uebersicht_Transaktionen -> uebersicht_transaktionen
    Gesamtuebers_Bestand     -> gesamtuebersicht_bestand
    Transaktionen_proSymbol  -> transaktionen_pro_symbol
    Abgleich_Bestand         -> abgleich_bestand
    DQ_Checks                -> dq_checks

Stufe B (ohne Gegenstueck in der Mappe):

    wertschriftenverzeichnis -> Positionen und Buchungen als Grundlage fuer
                                das Wertschriftenverzeichnis

Das Modul kennt kein DOM. Jede Funktion nimmt Bytes, Text oder Listen von
Dicts und gibt Listen von Dicts zurueck, damit sie ohne Browser testbar ist.
Mengen werden als Decimal gerechnet, weil Kryptobestaende bis zu acht
Dezimalstellen haben und Gleitkommarundung den Abgleich verfaelschen wuerde.
"""

import csv
import io
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

# --- Konstanten aus der Mappe ------------------------------------------------

CSV_TRENNZEICHEN = ";"
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

PFLICHTSPALTEN = (
    "Datum",
    "Transaktionen",
    "ISIN",
    "Anzahl",
    "Nettobetrag",
    "Waehrung",
)

# Schritt #"Filtered rows" im M-Code. Redundant zu den Regeln mit Kategorie
# "Ignorieren", aber bewusst 1:1 uebernommen, damit die Zeilenzahlen mit der
# Mappe vergleichbar bleiben.
HART_GEFILTERTE_BUCHUNGSARTEN = frozenset(
    {
        "Berichtigung Börsengeb.",
        "Depotgebühren",
        "Forex-Belastung",
        "Forex-Gutschrift",
        "Kartentransaktion",
        "Zahlung",
    }
)

# tbl_regeln, Stand der Mappe vom 11.11.2026.
STANDARD_REGELN = (
    ("Crypto Deposit", "Entgelt", 1, 1, 0),
    ("Dividende", "Entgelt", 1, 0, 0),
    ("Kauf", "Bestandesänderung", 1, 1, 0),
    ("Verkauf", "Bestandesänderung", -1, -1, 0),
    ("Wertpapierleihe", "Entgelt", 1, 0, 0),
    ("Zinsen auf Belastungen", "Abzug Schuldzinsen", -1, 0, 1),
    ("Zinsen auf Einlagen", "Entgelt", 1, 0, 1),
    ("Berichtigung Börsengeb.", "Ignorieren", 0, 0, 0),
    ("Depotgebühren", "Ignorieren", 0, 0, 0),
    ("Forex-Gutschrift", "Ignorieren", 0, 0, 0),
    ("Forex-Belastung", "Ignorieren", 0, 0, 0),
    ("Storno (Corporate Action)", "Ignorieren", 0, 0, 0),
    ("Zahlung", "Ignorieren", 0, 0, 0),
    ("Kartentransaktion", "Ignorieren", 0, 0, 0),
    ("Corporate Action (Storniert)", "Ignorieren", 0, 0, 0),
    ("Corporate Action", "Ignorieren", 0, 0, 0),
)

REGEL_SPALTEN = (
    "Buchungsart",
    "Kategorie",
    "Faktor",
    "Faktor_Menge",
    "Zuordnung_Vorjahr",
)

# Abschnitte des PDF, aus denen Positionen entstehen. "Liquiditaet" wird als
# Abschnitt erkannt, damit die Zeilen darunter keinem anderen Abschnitt
# zugeschlagen werden, ergibt aber keine Positionen: Cash-Konten gehoeren
# nicht in diesen Abgleich. Das entspricht der Mappe.
ABSCHNITTE_IM_ABGLEICH = ("Aktien", "Anlagefonds", "Kryptowährungen")

GRUND_OHNE_WAEHRUNG = "Keine Währung (als Storno behandelt)"
GRUND_BUCHUNGSART = "Buchungsart wird nicht ausgewertet"

ISIN_MUSTER = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b")
ZAHL_MUSTER = re.compile(r"^[+-]?\d[\d'’.,]*%?$")
STICHTAG_MUSTER = re.compile(r"Wertentwicklung per\s+(\d{2}\.\d{2}\.\d{4})")
WAEHRUNGSCODE_MUSTER = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")

# Abschnittstitel. Bewusst eng gefasst: "Aktien" allein steht auch in der
# Anlagekategorie-Uebersicht auf Seite 2 und darf dort nicht greifen.
ABSCHNITT_MUSTER = (
    (re.compile(r"^Aktien in [A-Z]{3}$"), "Aktien"),
    (re.compile(r"^Anlagefonds in [A-Z]{3}$"), "Anlagefonds"),
    (re.compile(r"^Kryptowährungen$"), "Kryptowährungen"),
    (re.compile(r"^Liquidität$"), "Liquidität"),
)

KRYPTO_PRAEFIX = "Position in "
KRYPTO_PSEUDO_ISIN_PRAEFIX = "EX0X"

ANFANGSBESTAND = "Anfangsbestand"
ENDBESTAND = "Endbestand"


# --- Hilfsfunktionen ---------------------------------------------------------


def parse_zahl(wert):
    """Liest "9'999.99", '-1234,56' oder '0.00000001' als Decimal."""
    if wert is None:
        return None
    text = str(wert).strip().rstrip("%")
    text = text.replace("’", "").replace("'", "").replace(" ", "")
    text = text.replace(" ", "")
    if not text or text in {"-", "--"}:
        return None
    if "," in text and "." in text:
        dezimal = "," if text.rfind(",") > text.rfind(".") else "."
        tausender = "." if dezimal == "," else ","
        text = text.replace(tausender, "").replace(dezimal, ".")
    else:
        text = text.replace(",", ".")
    try:
        zahl = Decimal(text)
    except InvalidOperation:
        return None
    return zahl if zahl.is_finite() else None


def formatiere_zahl(wert):
    """Decimal ohne Exponent und ohne nachlaufende Nullen."""
    if wert is None:
        return ""
    text = format(wert, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_datum(wert):
    """Swissquote schreibt 'TT-MM-JJJJ hh:mm:ss'. ISO und Punkte gehen auch."""
    if wert is None:
        return None
    text = str(wert).strip()
    if not text:
        return None
    datumsteil = text.split(" ")[0].split("T")[0]
    for muster in ("%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(datumsteil, muster).date()
        except ValueError:
            continue
    return None


def _dekodiere(rohdaten):
    for encoding in CSV_ENCODINGS:
        try:
            return rohdaten.decode(encoding)
        except UnicodeDecodeError:
            continue
    return rohdaten.decode("latin-1", errors="replace")


def _normalisiere_spalte(name):
    """'Waehrung' und 'Währung' sollen dieselbe Spalte treffen."""
    text = (name or "").strip()
    ersetzungen = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
    }
    for alt, neu in ersetzungen.items():
        text = text.replace(alt, neu)
    return text


def _zellen(zeile):
    """Layout-Text in Spalten zerlegen: zwei oder mehr Leerzeichen trennen."""
    return [teil for teil in re.split(r"\s{2,}", zeile.strip()) if teil]


def _ist_zahl(text):
    return bool(ZAHL_MUSTER.match(text.strip()))


# --- tbl_regeln --------------------------------------------------------------


def standard_regeln():
    """tbl_regeln als Liste von Dicts."""
    return [dict(zip(REGEL_SPALTEN, zeile)) for zeile in STANDARD_REGELN]


def lies_regeln(rohdaten):
    """Liest eine hochgeladene Regel-CSV mit den Spalten aus REGEL_SPALTEN."""
    text = _dekodiere(rohdaten)
    trenner = ";" if text.count(";") >= text.count(",") else ","
    leser = csv.DictReader(io.StringIO(text), delimiter=trenner)
    regeln = []
    for rohzeile in leser:
        zeile = {_normalisiere_spalte(k): v for k, v in rohzeile.items() if k}
        buchungsart = (zeile.get("Buchungsart") or "").strip()
        if not buchungsart:
            continue
        regeln.append(
            {
                "Buchungsart": buchungsart,
                "Kategorie": (zeile.get("Kategorie") or "").strip() or None,
                "Faktor": parse_zahl(zeile.get("Faktor")),
                "Faktor_Menge": parse_zahl(zeile.get("Faktor_Menge")),
                "Zuordnung_Vorjahr": parse_zahl(zeile.get("Zuordnung_Vorjahr"))
                or Decimal(0),
            }
        )
    if not regeln:
        raise ValueError(
            "In der Regeldatei wurde keine Zeile mit einer Buchungsart gefunden."
        )
    return regeln


def regeln_als_index(regeln):
    return {str(regel["Buchungsart"]).strip(): regel for regel in regeln}


def regeln_als_csv(regeln):
    puffer = io.StringIO()
    schreiber = csv.DictWriter(
        puffer, fieldnames=list(REGEL_SPALTEN), delimiter=";", extrasaction="ignore"
    )
    schreiber.writeheader()
    for regel in regeln:
        schreiber.writerow(
            {
                "Buchungsart": regel["Buchungsart"],
                "Kategorie": regel["Kategorie"] or "",
                "Faktor": formatiere_zahl(_als_decimal(regel["Faktor"])),
                "Faktor_Menge": formatiere_zahl(_als_decimal(regel["Faktor_Menge"])),
                "Zuordnung_Vorjahr": formatiere_zahl(
                    _als_decimal(regel["Zuordnung_Vorjahr"])
                ),
            }
        )
    return puffer.getvalue()


def _als_decimal(wert):
    if wert is None:
        return None
    if isinstance(wert, Decimal):
        return wert
    return Decimal(str(wert))


# --- transaktionen -----------------------------------------------------------


def lies_transaktionen(rohdaten):
    """Entspricht der Abfrage 'transaktionen'.

    Gibt (zeilen, hinweise, verworfen) zurueck: hinweise zaehlt, verworfen
    enthaelt jede verworfene Zeile mit dem Grund in der Spalte "Grund".
    """
    text = _dekodiere(rohdaten)
    leser = csv.DictReader(io.StringIO(text), delimiter=CSV_TRENNZEICHEN)
    if not leser.fieldnames:
        raise ValueError("Die CSV-Datei ist leer.")

    spalten = {_normalisiere_spalte(name): name for name in leser.fieldnames}
    fehlend = [name for name in PFLICHTSPALTEN if name not in spalten]
    if fehlend:
        raise ValueError(
            "In der CSV fehlen diese Spalten: "
            + ", ".join(fehlend)
            + ". Gefunden wurden: "
            + ", ".join(str(name) for name in leser.fieldnames)
        )

    def feld(zeile, name):
        quelle = spalten.get(name)
        if quelle is None:
            return ""
        return (zeile.get(quelle) or "").strip()

    zeilen = []
    verworfen = []
    hinweise = {
        "gelesen": 0,
        "ohne_waehrung": 0,
        "hart_gefiltert": 0,
        "datum_unlesbar": 0,
    }

    def verwirf(rohzeile, grund):
        verworfen.append(
            {
                "CSV_Zeile": hinweise["gelesen"] + 1,  # +1 fuer die Kopfzeile
                "Datum": parse_datum(feld(rohzeile, "Datum")),
                "Auftrag": feld(rohzeile, "Auftrag #"),
                "Transaktionen": feld(rohzeile, "Transaktionen"),
                "Symbol": feld(rohzeile, "Symbol"),
                "Name": feld(rohzeile, "Name"),
                "ISIN": feld(rohzeile, "ISIN").upper(),
                "Anzahl": parse_zahl(feld(rohzeile, "Anzahl")),
                "Nettobetrag": parse_zahl(feld(rohzeile, "Nettobetrag")),
                "Waehrung": feld(rohzeile, "Waehrung"),
                "Grund": grund,
            }
        )

    for rohzeile in leser:
        hinweise["gelesen"] += 1
        waehrung = feld(rohzeile, "Waehrung")
        if not waehrung:
            # Schritt "Stornos herausfiltern". Trifft auch nicht stornierte
            # Corporate Actions, deshalb zaehlen wir sie fuer den DQ-Check.
            hinweise["ohne_waehrung"] += 1
            verwirf(rohzeile, GRUND_OHNE_WAEHRUNG)
            continue

        buchungsart = feld(rohzeile, "Transaktionen")
        if buchungsart in HART_GEFILTERTE_BUCHUNGSARTEN:
            hinweise["hart_gefiltert"] += 1
            verwirf(rohzeile, GRUND_BUCHUNGSART)
            continue

        datum = parse_datum(feld(rohzeile, "Datum"))
        if datum is None:
            hinweise["datum_unlesbar"] += 1

        isin = feld(rohzeile, "ISIN").upper()
        if isin.startswith(KRYPTO_PSEUDO_ISIN_PRAEFIX) and len(isin) >= 9:
            schluessel = isin[6:9]
        else:
            schluessel = isin

        nettobetrag = parse_zahl(feld(rohzeile, "Nettobetrag"))
        zeilen.append(
            {
                "Datum": datum,
                "Auftrag": feld(rohzeile, "Auftrag #"),
                "Symbol": feld(rohzeile, "Symbol"),
                "Name": feld(rohzeile, "Name"),
                "Transaktionen": buchungsart,
                "ISIN": isin,
                "Schluessel": schluessel,
                "Anzahl": parse_zahl(feld(rohzeile, "Anzahl")),
                "Stueckpreis": parse_zahl(feld(rohzeile, "Stueckpreis")),
                # Replaced errors: Nettobetrag ohne Zahl wird 0.
                "Nettobetrag": nettobetrag if nettobetrag is not None else Decimal(0),
                "Kosten": parse_zahl(feld(rohzeile, "Kosten")),
                "Saldo": parse_zahl(feld(rohzeile, "Saldo")) or Decimal(0),
                "Waehrung": waehrung,
            }
        )

    return zeilen, hinweise, verworfen


# --- Uebersicht_Anfangsb / Uebersicht_Endb -----------------------------------


def lies_bestand(pdf_text, bezeichnung):
    """Entspricht Uebersicht_Anfangsb bzw. Uebersicht_Endb.

    Nimmt den mit extraction_mode="layout" extrahierten Text und gibt
    (positionen, stichtag) zurueck. Jede Position ist ein Dict mit
    Schluessel, Anzahl, Produkt_Name, Abschnitt, Stichtag, Stichtag_Bezeichnung.
    """
    if not (pdf_text or "").strip():
        raise ValueError(
            "Im PDF wurde kein auswählbarer Text gefunden. "
            "Vermutlich ein Scan; OCR wird nicht unterstützt."
        )

    stichtag_treffer = STICHTAG_MUSTER.search(pdf_text)
    if stichtag_treffer is None:
        raise ValueError(
            "Stichtag nicht gefunden: Der Titel 'Wertentwicklung per TT.MM.JJJJ' "
            "fehlt im PDF."
        )
    stichtag = datetime.strptime(stichtag_treffer.group(1), "%d.%m.%Y").date()

    positionen = []
    abschnitt = None

    for zeile in pdf_text.splitlines():
        zellen = _zellen(zeile)
        if not zellen:
            continue

        # Abschnittstitel stehen allein auf einer Zeile. Ueber Seitenumbrueche
        # hinweg bleibt der letzte Titel gueltig (entspricht Table.FillDown).
        if len(zellen) == 1:
            neuer_abschnitt = _erkenne_abschnitt(zellen[0])
            if neuer_abschnitt is not None:
                abschnitt = neuer_abschnitt
                continue

        if any(zelle.strip().casefold().startswith("total") for zelle in zellen):
            continue

        position = _lies_positionszeile(zellen, abschnitt)
        if position is None:
            continue
        position["Stichtag"] = stichtag
        position["Stichtag_Bezeichnung"] = bezeichnung
        positionen.append(position)

    return positionen, stichtag


def _erkenne_abschnitt(text):
    kandidat = text.strip()
    for muster, name in ABSCHNITT_MUSTER:
        if muster.match(kandidat):
            return name
    return None


def _lies_positionszeile(zellen, abschnitt):
    """Eine Zeile zu einer Position machen, oder None."""
    verbunden = "  ".join(zellen)

    # Wertschriften: ISIN irgendwo in der Zeile, Anzahl davor.
    isin_treffer = ISIN_MUSTER.search(verbunden.upper())
    if isin_treffer is not None and abschnitt in ("Aktien", "Anlagefonds"):
        isin = isin_treffer.group(0)
        index = next(
            (i for i, zelle in enumerate(zellen) if isin in zelle.upper()), None
        )
        if index is None or index == 0:
            return None
        davor = zellen[:index]
        anzahl = parse_zahl(davor[0])
        if anzahl is None:
            return None
        return {
            "Schluessel": isin,
            "Anzahl": anzahl,
            "Produkt_Name": " ".join(davor[1:]).strip(),
            "Abschnitt": abschnitt,
        }

    if abschnitt == "Kryptowährungen":
        return _lies_krypto(zellen)
    # "Liquiditaet" und alles ohne Abschnitt ergibt keine Position.
    return None


def _lies_krypto(zellen):
    """'SOL | Position in SOL | Wert | Wechselkurs | Bewertung | %'"""
    index = next(
        (i for i, zelle in enumerate(zellen) if zelle.strip().startswith(KRYPTO_PRAEFIX)),
        None,
    )
    if index is None:
        return None
    code = zellen[index].strip()[len(KRYPTO_PRAEFIX) :].strip().upper()
    if not WAEHRUNGSCODE_MUSTER.match(code):
        return None
    anzahl = next(
        (parse_zahl(zelle) for zelle in zellen[index + 1 :] if _ist_zahl(zelle)), None
    )
    if anzahl is None:
        return None
    return {
        "Schluessel": code,
        "Anzahl": anzahl,
        "Produkt_Name": zellen[index].strip(),
        "Abschnitt": "Kryptowährungen",
    }


def extrahiere_pdf_text(rohdaten):
    """Liest ein PDF mit pypdf im Layout-Modus. Lazy import fuer die Tests."""
    from io import BytesIO

    from pypdf import PdfReader

    leser = PdfReader(BytesIO(rohdaten))
    return "\n".join(
        seite.extract_text(extraction_mode="layout") or "" for seite in leser.pages
    )


# --- Uebersicht_Transaktionen ------------------------------------------------


def uebersicht_transaktionen(zeilen, regeln, stichtag_anfang, stichtag_ende):
    """Join auf tbl_regeln, Zuordnungsdatum und Periode."""
    index = regeln_als_index(regeln)
    ergebnis = []

    for zeile in zeilen:
        regel = index.get(zeile["Transaktionen"])
        kategorie = regel["Kategorie"] if regel else None
        faktor = _als_decimal(regel["Faktor"]) if regel else None
        faktor_menge = _als_decimal(regel["Faktor_Menge"]) if regel else None
        zuordnung_vorjahr = _als_decimal(regel["Zuordnung_Vorjahr"]) if regel else None

        anzahl = zeile["Anzahl"]
        if anzahl is not None and faktor is not None:
            anzahl_mit_vorzeichen = anzahl * faktor
        else:
            anzahl_mit_vorzeichen = None

        if kategorie is None or faktor is None:
            qualitaet = "prüfen(tbl_regeln)"
        else:
            qualitaet = "OK"

        datum = zeile["Datum"]
        zuordnungsdatum = datum
        if (
            datum is not None
            and zuordnung_vorjahr == 1
            and datum.day == 1
        ):
            # Regel aus tbl_regeln: Buchung am Monatsersten gehoert zum Vortag.
            zuordnungsdatum = datum - timedelta(days=1)

        neue_zeile = dict(zeile)
        neue_zeile.update(
            {
                "Kategorie": kategorie,
                "Faktor": faktor,
                "Faktor_Menge": faktor_menge,
                "Zuordnung_Vorjahr": zuordnung_vorjahr,
                "Anzahl_mitVorzeichen": anzahl_mit_vorzeichen,
                "q_Kategorisierung": qualitaet,
                "Zuordnungsdatum": zuordnungsdatum,
                "Periode": _periode(zuordnungsdatum, stichtag_anfang, stichtag_ende),
            }
        )
        ergebnis.append(neue_zeile)

    ergebnis.sort(key=lambda zeile: (zeile["Schluessel"], zeile["Datum"] or _MIN_DATUM))
    return ergebnis


_MIN_DATUM = datetime(1900, 1, 1).date()


def _periode(zuordnungsdatum, stichtag_anfang, stichtag_ende):
    if zuordnungsdatum is None or stichtag_anfang is None or stichtag_ende is None:
        return "Unbekannt"
    if zuordnungsdatum <= stichtag_anfang:
        return "Vorperiode"
    if zuordnungsdatum <= stichtag_ende:
        return "Periode"
    return "Folgeperiode"


# --- Gesamtuebers_Bestand ----------------------------------------------------


def gesamtuebersicht_bestand(anfangsbestand, endbestand):
    """Pivot ueber Anfangs- und Endbestand, nur Abschnitte mit Abgleich."""
    alle = [
        position
        for position in list(anfangsbestand) + list(endbestand)
        if position["Abschnitt"] in ABSCHNITTE_IM_ABGLEICH
    ]

    summen = {}
    for position in alle:
        schluessel = position["Schluessel"]
        eintrag = summen.setdefault(
            schluessel, {ANFANGSBESTAND: Decimal(0), ENDBESTAND: Decimal(0)}
        )
        eintrag[position["Stichtag_Bezeichnung"]] += position["Anzahl"]

    # Name und Abschnitt vom neuesten Stichtag je Schluessel.
    nach_stichtag = sorted(alle, key=lambda p: p["Stichtag"], reverse=True)
    stammdaten = {}
    for position in nach_stichtag:
        stammdaten.setdefault(
            position["Schluessel"],
            {
                "Produkt_Name": position["Produkt_Name"],
                "Abschnitt": position["Abschnitt"],
            },
        )

    ergebnis = []
    for schluessel in sorted(summen):
        anfang = summen[schluessel][ANFANGSBESTAND]
        ende = summen[schluessel][ENDBESTAND]
        stamm = stammdaten.get(schluessel, {})
        ergebnis.append(
            {
                "Abschnitt": stamm.get("Abschnitt"),
                "Produkt_Name": stamm.get("Produkt_Name"),
                "Identifier": schluessel,
                "Anfangsbestand": anfang,
                "Endbestand": ende,
                "Änderung_Bestand": ende - anfang,
            }
        )
    return ergebnis


# --- Transaktionen_proSymbol -------------------------------------------------


def transaktionen_pro_symbol(uebersicht):
    """Signierte Mengen der aktuellen Periode, gruppiert je Schluessel."""
    gruppen = {}
    for zeile in uebersicht:
        faktor_menge = zeile["Faktor_Menge"]
        if faktor_menge is not None and faktor_menge == 0:
            continue
        if zeile["Periode"] != "Periode":
            continue

        schluessel = zeile["Schluessel"]
        gruppe = gruppen.setdefault(
            schluessel,
            {
                "Name": None,
                "Schluessel": schluessel,
                "Veraenderung_Transaktionen": Decimal(0),
                "Anzahl_Transaktionen": 0,
            },
        )
        gruppe["Anzahl_Transaktionen"] += 1
        anzahl = zeile["Anzahl"]
        if anzahl is not None and faktor_menge is not None:
            gruppe["Veraenderung_Transaktionen"] += abs(anzahl) * faktor_menge
        name = (zeile.get("Name") or "").strip()
        if name and (gruppe["Name"] is None or name > gruppe["Name"]):
            gruppe["Name"] = name

    return [gruppen[schluessel] for schluessel in sorted(gruppen)]


# --- Abgleich_Bestand --------------------------------------------------------


def abgleich_bestand(bestand, pro_symbol):
    """Full outer join Bestand gegen Transaktionen, mit Differenz und Status."""
    bestand_index = {zeile["Identifier"]: zeile for zeile in bestand}
    symbol_index = {zeile["Schluessel"]: zeile for zeile in pro_symbol}

    ergebnis = []
    for schluessel in sorted(set(bestand_index) | set(symbol_index)):
        links = bestand_index.get(schluessel)
        rechts = symbol_index.get(schluessel)

        anfang = links["Anfangsbestand"] if links else Decimal(0)
        ende = links["Endbestand"] if links else Decimal(0)
        aenderung = links["Änderung_Bestand"] if links else Decimal(0)
        veraenderung = (
            rechts["Veraenderung_Transaktionen"] if rechts else Decimal(0)
        )
        anzahl_transaktionen = rechts["Anzahl_Transaktionen"] if rechts else 0
        name = (links or {}).get("Produkt_Name") or (rechts or {}).get("Name") or ""

        differenz = (aenderung - veraenderung).quantize(Decimal("1E-8"))
        ergebnis.append(
            {
                "Identifier": schluessel,
                "Produkt_Name": name,
                "Abschnitt": (links or {}).get("Abschnitt") or "",
                "Anfangsbestand": anfang,
                "Endbestand": ende,
                "Änderung_Bestand": aenderung,
                "Veraenderung_Transaktionen": veraenderung,
                "Anzahl_Transaktionen": anzahl_transaktionen,
                "Differenz": differenz,
                "Status": "OK" if differenz == 0 else "Fehler",
            }
        )
    return ergebnis


# --- DQ_Checks ---------------------------------------------------------------


def dq_checks(abgleich, uebersicht, hinweise=None):
    """Ein Test je Zeile. Ergebnis 'OK', wenn keine Zeile betroffen ist."""
    hinweise = hinweise or {}
    t1 = sum(1 for zeile in abgleich if zeile["Status"] != "OK")
    t2 = sum(1 for zeile in uebersicht if zeile["q_Kategorisierung"] != "OK")
    t3 = int(hinweise.get("ohne_waehrung", 0))
    t4 = int(hinweise.get("datum_unlesbar", 0))

    # "Hinweis" statt "Fehler", wo der Befund erwartbar ist und nur gesehen
    # werden muss: Zeilen ohne Waehrung sind meist echte Stornos, aber der
    # Filter trifft auch nicht stornierte Corporate Actions.
    tests = [
        ("Abgleich Bestand vs. Transaktionen", t1, "Fehler"),
        ("Regel für jede Buchungsart", t2, "Fehler"),
        ("Zeilen ohne Währung verworfen", t3, "Hinweis"),
        ("Datum lesbar", t4, "Fehler"),
    ]
    return [
        {
            "Test": name,
            "Betroffene_Zeilen": anzahl,
            "Ergebnis": "OK" if anzahl == 0 else stufe,
        }
        for name, anzahl, stufe in tests
    ]


# --- Stufe B: Grundlage Wertschriftenverzeichnis ----------------------------

KATEGORIE_IGNORIEREN = "Ignorieren"

WV_SPALTEN = (
    "Abschnitt",
    "Identifier",
    "Bezeichnung",
    "Stueck_Anfang",
    "Stueck_Ende",
    "Buchungen",
)

WV_BUCHUNG_SPALTEN = (
    "Identifier",
    "Bezeichnung",
    "Datum",
    "Transaktionen",
    "Anzahl",
    "Stueckpreis",
    "Kosten",
    "Nettobetrag",
    "Waehrung",
)


def wertschriftenverzeichnis(bestand, uebersicht):
    """Grundlage fuer das Wertschriftenverzeichnis, ohne steuerliche Wertung.

    bestand ist das Ergebnis von gesamtuebersicht_bestand. Gibt
    (positionen, buchungen) zurueck:

    positionen: jede Wertschrift mit Bestand am Anfang oder Ende oder mit
        Buchungen in der Periode, mit Stueckzahl am Anfang und Ende.
    buchungen: jede Buchung der Periode, die zu einer Wertschrift gehoert
        (Kauf, Verkauf, Dividende, Zugang usw.), ohne die als "Ignorieren"
        eingestuften. Cash-Konten haben keinen Identifier und fehlen.
    """
    namen = {}
    positionen = {}
    for zeile in bestand:
        positionen[zeile["Identifier"]] = {
            "Abschnitt": zeile["Abschnitt"] or "",
            "Identifier": zeile["Identifier"],
            "Bezeichnung": zeile["Produkt_Name"] or "",
            "Stueck_Anfang": zeile["Anfangsbestand"],
            "Stueck_Ende": zeile["Endbestand"],
            "Buchungen": 0,
        }
        namen[zeile["Identifier"]] = zeile["Produkt_Name"] or ""

    buchungen = []
    for zeile in uebersicht:
        identifier = zeile["Schluessel"]
        if (
            zeile["Periode"] != "Periode"
            or not identifier
            or zeile["Kategorie"] == KATEGORIE_IGNORIEREN
        ):
            continue
        name = namen.get(identifier) or zeile.get("Name") or ""
        position = positionen.setdefault(
            identifier,
            {
                "Abschnitt": "",
                "Identifier": identifier,
                "Bezeichnung": name,
                "Stueck_Anfang": Decimal(0),
                "Stueck_Ende": Decimal(0),
                "Buchungen": 0,
            },
        )
        position["Buchungen"] += 1
        buchungen.append(
            {
                "Identifier": identifier,
                "Bezeichnung": name,
                "Datum": zeile["Datum"],
                "Transaktionen": zeile["Transaktionen"],
                "Anzahl": zeile["Anzahl"],
                "Stueckpreis": zeile.get("Stueckpreis"),
                "Kosten": zeile.get("Kosten"),
                "Nettobetrag": zeile["Nettobetrag"],
                "Waehrung": zeile["Waehrung"],
            }
        )

    buchungen.sort(key=lambda b: (b["Identifier"], b["Datum"] or _MIN_DATUM))
    return [positionen[k] for k in sorted(positionen)], buchungen


# --- Gesamtlauf --------------------------------------------------------------


def auswerten(csv_rohdaten, anfangs_pdf_text, end_pdf_text, regeln=None):
    """Fuehrt die ganze Kette aus und gibt alle Zwischenergebnisse zurueck."""
    regeln = regeln or standard_regeln()
    zeilen, hinweise, verworfen = lies_transaktionen(csv_rohdaten)
    anfang, stichtag_anfang = lies_bestand(anfangs_pdf_text, ANFANGSBESTAND)
    ende, stichtag_ende = lies_bestand(end_pdf_text, ENDBESTAND)

    uebersicht = uebersicht_transaktionen(
        zeilen, regeln, stichtag_anfang, stichtag_ende
    )
    bestand = gesamtuebersicht_bestand(anfang, ende)
    pro_symbol = transaktionen_pro_symbol(uebersicht)
    abgleich = abgleich_bestand(bestand, pro_symbol)
    wv, wv_buchungen = wertschriftenverzeichnis(bestand, uebersicht)

    return {
        "hinweise": hinweise,
        "verworfene_transaktionen": verworfen,
        "stichtag_anfang": stichtag_anfang,
        "stichtag_ende": stichtag_ende,
        "anfangsbestand": anfang,
        "endbestand": ende,
        "uebersicht_transaktionen": uebersicht,
        "gesamtuebersicht_bestand": bestand,
        "transaktionen_pro_symbol": pro_symbol,
        "abgleich_bestand": abgleich,
        "dq_checks": dq_checks(abgleich, uebersicht, hinweise),
        "wertschriftenverzeichnis": wv,
        "wv_buchungen": wv_buchungen,
    }


def als_csv(zeilen, spalten):
    """Liste von Dicts als CSV-Text, Semikolon getrennt, mit BOM fuer Excel."""
    puffer = io.StringIO()
    schreiber = csv.DictWriter(
        puffer, fieldnames=list(spalten), delimiter=";", extrasaction="ignore"
    )
    schreiber.writeheader()
    for zeile in zeilen:
        ausgabe = {}
        for spalte in spalten:
            wert = zeile.get(spalte)
            if isinstance(wert, Decimal):
                ausgabe[spalte] = formatiere_zahl(wert)
            elif wert is None:
                ausgabe[spalte] = ""
            else:
                ausgabe[spalte] = str(wert)
        schreiber.writerow(ausgabe)
    return "﻿" + puffer.getvalue()
