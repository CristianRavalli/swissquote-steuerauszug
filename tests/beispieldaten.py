"""Synthetische Beispieldaten. Enthaelt keine echten Kontodaten.

Die Daten bilden bewusst die Eigenheiten der echten Dateien nach:

CSV
  * Trennzeichen ";", Encoding ISO-8859-1, Datum "TT-MM-JJJJ hh:mm:ss"
  * Crypto Deposit mit Nettobetrag "-" und leerem Saldo
  * eine Zeile mit leerer Waehrung (wird als Storno verworfen)
  * Teilausfuehrung: zwei Zeilen mit derselben Auftragsnummer
  * Krypto-Pseudo-ISIN EX0X00SOL000
  * "Berichtigung Boersengeb." zu einem Verkauf (wird hart gefiltert)
  * Buchung am 01.01. mit Zuordnung_Vorjahr = 1

PDF
  * Layout-Text wie pypdf ihn mit extraction_mode="layout" liefert
  * Abschnitte Liquiditaet, Kryptowaehrungen, Aktien in USD, Anlagefonds in CHF
  * "Aktien in USD" laeuft ueber einen Seitenumbruch und wird dort nicht
    wiederholt, nur die Spaltenkopfzeile
  * Zusammenfassungszeilen der Anlagekategorien, die nicht als Abschnitts-
    titel gelesen werden duerfen
  * "Total ..." Zeilen und Fusszeilen
"""

from decimal import Decimal

ANFANGS_STICHTAG = "31.12.2024"
END_STICHTAG = "31.12.2025"

# Spaltenreihenfolge wie im Swissquote-Export.
CSV_KOPF = (
    "Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;"
    "Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung"
)

CSV_ZEILEN = (
    # Teilausfuehrung: ein Auftrag, zwei Zeilen, zusammen 5 Stueck.
    "12-03-2025 10:15:02;800001;Kauf;ALPH;ALPHA CORP;US0000000001;3;"
    "100.00;1.50;0;-301.50;4'698.50;USD",
    "12-03-2025 10:15:44;800001;Kauf;ALPH;ALPHA CORP;US0000000001;2;"
    "100.00;1.50;0;-201.50;4'497.00;USD",
    # Verkauf plus nachtraegliche Gebuehrenberichtigung.
    "04-07-2025 14:02:11;800002;Verkauf;BETA;BETA INC;US0000000019;4;"
    "50.00;1.20;0;198.80;4'695.80;USD",
    "05-07-2025 09:00:00;800002;Berichtigung Börsengeb.;BETA;BETA INC;"
    "US0000000019;0;0.00;0.40;0;-0.40;4'695.40;USD",
    # Staking-Zufluesse: Nettobetrag "-", Saldo leer.
    "15-05-2025 03:00:00;800003;Crypto Deposit;SOL;SOLANA;EX0X00SOL000;"
    "0.25;0.00;0.00;0;-;;SOL",
    "15-11-2025 03:00:00;800004;Crypto Deposit;SOL;SOLANA;EX0X00SOL000;"
    "0.25;0.00;0.00;0;-;;SOL",
    # Ertrag ohne Mengenwirkung.
    "20-06-2025 00:00:00;800005;Dividende;ALPH;ALPHA CORP;US0000000001;10;"
    "0.00;0.45;0;3.00;4'698.40;USD",
    # Zinsen am 01.01.2026 gehoeren laut Regel zum 31.12.2025.
    "01-01-2026 00:00:00;800006;Zinsen auf Einlagen;;Kontokorrent CHF;;0;"
    "0.00;0.00;0;1.20;1'201.20;CHF",
    # Storno: leere Waehrung, wird verworfen.
    "09-09-2025 00:00:00;800007;Corporate Action;BETA;BETA INC;"
    "US0000000019;0;0.00;0.00;0;0.00;0.00;",
    # Wird hart gefiltert.
    "11-11-2025 12:00:00;800008;Kartentransaktion;;Laden;;0;"
    "0.00;0.00;0;-25.00;1'176.20;CHF",
    "02-02-2025 08:00:00;800009;Depotgebühren;;;;0;"
    "0.00;0.00;0;-9.00;1'167.20;CHF",
    # Vorperiode und Folgeperiode.
    "10-06-2024 11:00:00;700001;Kauf;GAMM;GAMMA FUND;CH0000000013;100;"
    "10.00;1.00;0;-1'001.00;2'000.00;CHF",
    "03-02-2026 11:00:00;900001;Kauf;ALPH;ALPHA CORP;US0000000001;7;"
    "110.00;1.50;0;-771.50;3'000.00;USD",
)


def beispiel_csv():
    """Transaktions-CSV als Bytes in ISO-8859-1, wie Swissquote sie liefert."""
    text = "\r\n".join((CSV_KOPF,) + CSV_ZEILEN) + "\r\n"
    return text.encode("latin-1")


def _spalten(*zellen):
    """Zeile im Layout-Stil: Spalten durch mehrere Leerzeichen getrennt."""
    return "   ".join(zellen)


def _kopfzeile_wertschriften():
    return _spalten(
        "         Anzahl",
        "Wertpapier",
        "ISIN",
        "Durchschnittspreis",
        "Marktpreis",
        "Kursdatum",
        "Bewertung in USD",
        "Wechselkurs",
        "Bewertung in CHF",
        "%",
    )


def _fusszeilen():
    return [
        "Beispielbank AG, 1 Beispielstrasse, CH-0000 Beispielstadt",
        "Telefon : 0000 00 00 00",
    ]


def beispiel_pdf_text(stichtag, liquiditaet, krypto, aktien, fonds):
    """Baut Layout-Text wie pypdf ihn aus dem echten PDF liefert.

    liquiditaet: Liste (Waehrung, Referenz, Beschreibung, Betrag)
    krypto:      Liste (Code, Menge)
    aktien:      Liste (Anzahl, Name, ISIN) in USD
    fonds:       Liste (Anzahl, Name, ISIN) in CHF
    """
    zeilen = []

    # Seite 1: Titel.
    zeilen.append(_spalten("      Portfolio-Wertentwicklung per " + stichtag))
    zeilen.append("")

    # Seite 2: Uebersicht. Diese Zeilen duerfen keine Abschnitte setzen.
    zeilen.append(_spalten("  1.", "Übersicht"))
    zeilen.append(_spalten("       Anlagekategorie", "CHF"))
    zeilen.append(_spalten("       Liquidität", "1'200.00"))
    zeilen.append(_spalten("       Aktien", "2'500.00"))
    zeilen.append(_spalten("       Anlagefonds", "1'000.00"))
    zeilen.append(_spalten("       Kryptowährungen", "300.00"))
    zeilen.append(_spalten("       Total", "5'000.00", "100.00"))
    zeilen.extend(_fusszeilen())
    zeilen.append("")

    # Seite 3: Liquiditaet, Krypto, Aktien in USD (Anfang).
    zeilen.append(_spalten("  2.", "Asset-Allokation"))
    zeilen.append("Liquidität")
    zeilen.append(
        _spalten(
            "        Währung",
            "Referenz",
            "Beschreibung",
            "Wert",
            "Wechselkurs",
            "Bewertung in CHF",
            "%",
        )
    )
    total_chf = Decimal(0)
    for eintrag in liquiditaet:
        # (Waehrung, Referenz, Beschreibung, Wert[, Wechselkurs, Bewertung CHF])
        waehrung, referenz, beschreibung, betrag = eintrag[:4]
        kurs = eintrag[4] if len(eintrag) > 4 else "1.00000"
        chf = eintrag[5] if len(eintrag) > 5 else betrag
        total_chf += Decimal(chf.replace("'", ""))
        zeilen.append(
            _spalten(
                "             " + waehrung,
                referenz,
                beschreibung,
                betrag,
                kurs,
                chf,
                "24.00",
            )
        )
    zeilen.append(
        _spalten("                    Total Liquidität", f"{total_chf:,.2f}".replace(",", "'"), "24.00")
    )

    zeilen.append("Kryptowährungen")
    zeilen.append(
        _spalten(
            "        Währung",
            "Beschreibung",
            "Wert",
            "Wechselkurs (1)",
            "Bewertung in CHF",
            "%",
        )
    )
    for code, menge in krypto:
        zeilen.append(
            _spalten(
                "             " + code,
                "Position in " + code,
                menge,
                "150.0000000",
                "300.00",
                "6.00",
            )
        )
    zeilen.append(
        _spalten("                    Total kryptowährungen", "300.00", "6.00")
    )

    zeilen.append("Aktien in USD")
    zeilen.append(_kopfzeile_wertschriften())
    for anzahl, name, isin in aktien[:1]:
        zeilen.append(
            _spalten(
                "            " + anzahl,
                name,
                isin,
                "100.000",
                "110.000",
                "30.12.2025",
                "1'100.00",
                "0.90000",
                "990.00",
                "19.80",
            )
        )
    zeilen.extend(_fusszeilen())
    zeilen.append("")

    # Seite 4: Fortsetzung von "Aktien in USD" ohne Abschnittstitel.
    zeilen.append(
        _spalten("          Portfolio-Wertentwicklung per " + stichtag + " - Muster")
    )
    zeilen.append(_kopfzeile_wertschriften())
    for anzahl, name, isin in aktien[1:]:
        zeilen.append(
            _spalten(
                "            " + anzahl,
                name,
                isin,
                "50.000",
                "55.000",
                "30.12.2025",
                "220.00",
                "0.90000",
                "198.00",
                "3.96",
            )
        )
    zeilen.append(_spalten("                    Total Aktien in USD", "1'320.00", "23.76"))

    zeilen.append("Anlagefonds in CHF")
    zeilen.append(
        _spalten(
            "         Anzahl",
            "Wertpapier",
            "ISIN",
            "Durchschnittspreis",
            "Marktpreis",
            "Kursdatum",
            "Bewertung in CHF",
            "%",
        )
    )
    for anzahl, name, isin in fonds:
        zeilen.append(
            _spalten(
                "            " + anzahl,
                name,
                isin,
                "10.000",
                "10.000",
                "30.12.2025",
                "1'000.00",
                "20.00",
            )
        )
    zeilen.append(
        _spalten("                    Total Anlagefonds in CHF", "1'000.00", "20.00")
    )
    zeilen.extend(_fusszeilen())

    return "\n".join(zeilen)


def beispiel_anfangsbestand():
    return beispiel_pdf_text(
        ANFANGS_STICHTAG,
        liquiditaet=[("CHF", "123456789", "Kontokorrent (CHF)", "1'000.00")],
        krypto=[("SOL", "1.50000000")],
        aktien=[("10", "ALPHA CORP", "US0000000001"), ("4", "BETA INC", "US0000000019")],
        fonds=[("100", "GAMMA FUND", "CH0000000013")],
    )


def beispiel_endbestand():
    return beispiel_pdf_text(
        END_STICHTAG,
        liquiditaet=[
            ("CHF", "123456789", "Kontokorrent (CHF)", "1'200.00"),
            ("USD", "123456790", "Kontokorrent (USD)", "1'000.00", "0.80000", "800.00"),
        ],
        krypto=[("SOL", "2.00000000")],
        # BETA ist verkauft und steht nicht mehr im Endbestand.
        aktien=[("15", "ALPHA CORP", "US0000000001")],
        fonds=[("100", "GAMMA FUND", "CH0000000013")],
    )
