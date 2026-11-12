"""Tests gegen synthetische Beispieldaten. Keine echten Kontodaten.

Laufen lassen aus dem Projektordner:

    python3 -m unittest discover -s tests -t .
"""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline  # noqa: E402
from tests import beispieldaten  # noqa: E402


def _als_dict(zeilen, schluesselspalte, wertspalte):
    return {zeile[schluesselspalte]: zeile[wertspalte] for zeile in zeilen}


class TestZahlenUndDatum(unittest.TestCase):
    def test_schweizer_tausendertrennzeichen(self):
        self.assertEqual(pipeline.parse_zahl("9'999.99"), Decimal("9999.99"))
        self.assertEqual(pipeline.parse_zahl("9’999.99"), Decimal("9999.99"))

    def test_komma_als_dezimaltrennzeichen(self):
        self.assertEqual(pipeline.parse_zahl("-1234,56"), Decimal("-1234.56"))

    def test_acht_dezimalstellen_bleiben_exakt(self):
        self.assertEqual(pipeline.parse_zahl("0.00000001"), Decimal("1E-8"))

    def test_bindestrich_ist_keine_zahl(self):
        self.assertIsNone(pipeline.parse_zahl("-"))
        self.assertIsNone(pipeline.parse_zahl(""))

    def test_swissquote_datumsformat(self):
        self.assertEqual(pipeline.parse_datum("12-03-2025 10:15:02"), date(2025, 3, 12))

    def test_weitere_datumsformate(self):
        self.assertEqual(pipeline.parse_datum("31.12.2025"), date(2025, 12, 31))
        self.assertEqual(pipeline.parse_datum("2025-12-31"), date(2025, 12, 31))
        self.assertIsNone(pipeline.parse_datum("kein Datum"))


class TestTransaktionen(unittest.TestCase):
    def setUp(self):
        self.zeilen, self.hinweise, self.verworfen = pipeline.lies_transaktionen(
            beispieldaten.beispiel_csv()
        )

    def test_zeilen_werden_gefiltert(self):
        self.assertEqual(self.hinweise["gelesen"], 13)
        self.assertEqual(self.hinweise["ohne_waehrung"], 1)
        self.assertEqual(self.hinweise["hart_gefiltert"], 3)
        self.assertEqual(self.hinweise["datum_unlesbar"], 0)
        self.assertEqual(len(self.zeilen), 9)

    def test_verworfene_zeilen_haben_einen_grund(self):
        self.assertEqual(len(self.verworfen), 4)
        nach_grund = {}
        for zeile in self.verworfen:
            nach_grund.setdefault(zeile["Grund"], []).append(zeile["Transaktionen"])
        self.assertEqual(
            nach_grund[pipeline.GRUND_OHNE_WAEHRUNG], ["Corporate Action"]
        )
        self.assertEqual(
            sorted(nach_grund[pipeline.GRUND_BUCHUNGSART]),
            ["Berichtigung Börsengeb.", "Depotgebühren", "Kartentransaktion"],
        )

    def test_verworfene_zeilen_tragen_die_csv_zeilennummer(self):
        # Zeile 1 ist die Kopfzeile; die Gebuehrenberichtigung steht an
        # vierter Datenstelle, also in CSV-Zeile 5.
        berichtigung = next(
            z for z in self.verworfen if z["Transaktionen"].startswith("Berichtigung")
        )
        self.assertEqual(berichtigung["CSV_Zeile"], 5)
        self.assertEqual(berichtigung["Datum"], date(2025, 7, 5))

    def test_verworfen_plus_ausgewertet_ergibt_alle_zeilen(self):
        self.assertEqual(
            len(self.verworfen) + len(self.zeilen), self.hinweise["gelesen"]
        )

    def test_krypto_pseudo_isin_wird_zum_code(self):
        krypto = [z for z in self.zeilen if z["Transaktionen"] == "Crypto Deposit"]
        self.assertEqual(len(krypto), 2)
        for zeile in krypto:
            self.assertEqual(zeile["ISIN"], "EX0X00SOL000")
            self.assertEqual(zeile["Schluessel"], "SOL")

    def test_nettobetrag_ohne_zahl_wird_null(self):
        krypto = next(z for z in self.zeilen if z["Transaktionen"] == "Crypto Deposit")
        self.assertEqual(krypto["Nettobetrag"], Decimal(0))
        self.assertEqual(krypto["Saldo"], Decimal(0))

    def test_teilausfuehrung_bleibt_zwei_zeilen(self):
        auftrag = [z for z in self.zeilen if z["Auftrag"] == "800001"]
        self.assertEqual(len(auftrag), 2)
        self.assertEqual(
            sum(z["Anzahl"] for z in auftrag), Decimal(5)
        )

    def test_umlaute_in_der_kopfzeile(self):
        zeile = self.zeilen[0]
        self.assertIn(zeile["Waehrung"], {"USD", "CHF", "SOL"})

    def test_fehlende_spalte_wird_gemeldet(self):
        with self.assertRaises(ValueError) as fehler:
            pipeline.lies_transaktionen(b"Datum;Anzahl\r\n01-01-2025;1\r\n")
        self.assertIn("Transaktionen", str(fehler.exception))


class TestBestand(unittest.TestCase):
    def setUp(self):
        self.anfang, self.stichtag_anfang = pipeline.lies_bestand(
            beispieldaten.beispiel_anfangsbestand(), pipeline.ANFANGSBESTAND
        )
        self.ende, self.stichtag_ende = pipeline.lies_bestand(
            beispieldaten.beispiel_endbestand(), pipeline.ENDBESTAND
        )

    def test_stichtag_aus_dem_titel(self):
        self.assertEqual(self.stichtag_anfang, date(2024, 12, 31))
        self.assertEqual(self.stichtag_ende, date(2025, 12, 31))

    def test_abschnitte_mit_positionen(self):
        abschnitte = {position["Abschnitt"] for position in self.anfang}
        self.assertEqual(abschnitte, {"Kryptowährungen", "Aktien", "Anlagefonds"})

    def test_positionen_im_anfangsbestand(self):
        mengen = _als_dict(self.anfang, "Schluessel", "Anzahl")
        self.assertEqual(
            mengen,
            {
                "SOL": Decimal("1.50000000"),
                "US0000000001": Decimal("10"),
                "US0000000019": Decimal("4"),
                "CH0000000013": Decimal("100"),
            },
        )

    def test_abschnitt_laeuft_ueber_den_seitenumbruch(self):
        # BETA INC steht auf der zweiten Seite, ohne wiederholten Titel.
        beta = next(p for p in self.anfang if p["Schluessel"] == "US0000000019")
        self.assertEqual(beta["Abschnitt"], "Aktien")
        self.assertEqual(beta["Produkt_Name"], "BETA INC")

    def test_uebersichtszeilen_setzen_keinen_abschnitt(self):
        # Seite 2 nennt "Aktien" und "Liquiditaet" mit Summen. Daraus darf
        # keine Position entstehen.
        self.assertNotIn("", {p["Schluessel"] for p in self.anfang})
        self.assertEqual(len(self.anfang), 4)

    def test_totalzeilen_werden_uebersprungen(self):
        self.assertFalse(
            any(
                str(p["Produkt_Name"]).casefold().startswith("total")
                for p in self.anfang
            )
        )

    def test_cash_konten_ergeben_keine_positionen(self):
        # Der Abschnitt Liquiditaet steht im PDF, wird aber uebersprungen.
        for bestand in (self.anfang, self.ende):
            self.assertNotIn("CHF", {p["Schluessel"] for p in bestand})
            self.assertNotIn("Liquidität", {p["Abschnitt"] for p in bestand})
            self.assertNotIn("123456789", str(bestand))

    def test_zeilen_nach_liquiditaet_landen_im_richtigen_abschnitt(self):
        # Direkt nach dem Liquiditaets-Abschnitt folgt Krypto. Der Wechsel
        # muss greifen, sonst fehlt SOL.
        self.assertIn("SOL", {p["Schluessel"] for p in self.anfang})

    def test_fehlender_stichtag_wird_gemeldet(self):
        with self.assertRaises(ValueError) as fehler:
            pipeline.lies_bestand("Aktien in USD\n10  X  US0000000001  1", "Endbestand")
        self.assertIn("Stichtag", str(fehler.exception))

    def test_leeres_pdf_wird_gemeldet(self):
        with self.assertRaises(ValueError) as fehler:
            pipeline.lies_bestand("   ", "Endbestand")
        self.assertIn("Scan", str(fehler.exception))


class TestGesamtlauf(unittest.TestCase):
    def setUp(self):
        self.ergebnis = pipeline.auswerten(
            beispieldaten.beispiel_csv(),
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )

    def test_perioden_nach_stichtag(self):
        perioden = {}
        for zeile in self.ergebnis["uebersicht_transaktionen"]:
            perioden.setdefault(zeile["Periode"], 0)
            perioden[zeile["Periode"]] += 1
        self.assertEqual(perioden.get("Vorperiode"), 1)
        self.assertEqual(perioden.get("Folgeperiode"), 1)
        self.assertEqual(perioden.get("Periode"), 7)

    def test_buchung_am_monatsersten_zaehlt_zum_vortag(self):
        zinsen = next(
            zeile
            for zeile in self.ergebnis["uebersicht_transaktionen"]
            if zeile["Transaktionen"] == "Zinsen auf Einlagen"
        )
        self.assertEqual(zinsen["Datum"], date(2026, 1, 1))
        self.assertEqual(zinsen["Zuordnungsdatum"], date(2025, 12, 31))
        self.assertEqual(zinsen["Periode"], "Periode")

    def test_verworfene_transaktionen_im_ergebnis(self):
        self.assertEqual(len(self.ergebnis["verworfene_transaktionen"]), 4)

    def test_liquiditaet_ist_nicht_im_abgleich(self):
        identifier = {z["Identifier"] for z in self.ergebnis["abgleich_bestand"]}
        self.assertNotIn("CHF", identifier)
        self.assertEqual(
            identifier,
            {"US0000000001", "US0000000019", "CH0000000013", "SOL"},
        )

    def test_bestandsaenderung(self):
        aenderungen = _als_dict(
            self.ergebnis["gesamtuebersicht_bestand"],
            "Identifier",
            "Änderung_Bestand",
        )
        self.assertEqual(aenderungen["US0000000001"], Decimal(5))
        self.assertEqual(aenderungen["US0000000019"], Decimal(-4))
        self.assertEqual(aenderungen["CH0000000013"], Decimal(0))
        self.assertEqual(aenderungen["SOL"], Decimal("0.5"))

    def test_transaktionen_pro_symbol(self):
        pro_symbol = {
            zeile["Schluessel"]: zeile
            for zeile in self.ergebnis["transaktionen_pro_symbol"]
        }
        self.assertEqual(
            pro_symbol["US0000000001"]["Veraenderung_Transaktionen"], Decimal(5)
        )
        self.assertEqual(pro_symbol["US0000000001"]["Anzahl_Transaktionen"], 2)
        self.assertEqual(
            pro_symbol["US0000000019"]["Veraenderung_Transaktionen"], Decimal(-4)
        )
        self.assertEqual(pro_symbol["SOL"]["Veraenderung_Transaktionen"], Decimal("0.5"))
        self.assertEqual(pro_symbol["SOL"]["Anzahl_Transaktionen"], 2)
        # Dividende und Zinsen haben Faktor_Menge 0 und zaehlen nicht mit.
        self.assertNotIn("", pro_symbol)

    def test_abgleich_geht_auf(self):
        for zeile in self.ergebnis["abgleich_bestand"]:
            self.assertEqual(zeile["Differenz"], Decimal(0), zeile["Identifier"])
            self.assertEqual(zeile["Status"], "OK", zeile["Identifier"])

    def test_dq_checks(self):
        checks = _als_dict(self.ergebnis["dq_checks"], "Test", "Ergebnis")
        self.assertEqual(checks["Abgleich Bestand vs. Transaktionen"], "OK")
        self.assertEqual(checks["Regel für jede Buchungsart"], "OK")
        self.assertEqual(checks["Datum lesbar"], "OK")
        # Die verworfene Zeile ohne Waehrung ist ein Hinweis, kein Fehler.
        self.assertEqual(checks["Zeilen ohne Währung verworfen"], "Hinweis")
        betroffene = _als_dict(
            self.ergebnis["dq_checks"], "Test", "Betroffene_Zeilen"
        )
        self.assertEqual(betroffene["Zeilen ohne Währung verworfen"], 1)

    def test_csv_export_hat_bom_und_semikolon(self):
        text = pipeline.als_csv(
            self.ergebnis["abgleich_bestand"],
            ("Identifier", "Differenz", "Status"),
        )
        self.assertTrue(text.startswith("﻿"))
        self.assertIn("Identifier;Differenz;Status", text)


class TestWertschriftenverzeichnis(unittest.TestCase):
    def setUp(self):
        ergebnis = pipeline.auswerten(
            beispieldaten.beispiel_csv(),
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )
        self.wv = {z["Identifier"]: z for z in ergebnis["wertschriftenverzeichnis"]}
        self.buchungen = ergebnis["wv_buchungen"]

    def test_alle_wertschriften_ohne_cash(self):
        self.assertEqual(
            set(self.wv), {"US0000000001", "US0000000019", "CH0000000013", "SOL"}
        )

    def test_stueck_anfang_und_ende(self):
        self.assertEqual(self.wv["US0000000001"]["Stueck_Anfang"], Decimal(10))
        self.assertEqual(self.wv["US0000000001"]["Stueck_Ende"], Decimal(15))
        # Verkauft: bleibt mit Ende 0 in der Liste.
        self.assertEqual(self.wv["US0000000019"]["Stueck_Ende"], Decimal(0))

    def test_buchungen_der_periode(self):
        arten = [
            (b["Identifier"], b["Transaktionen"]) for b in self.buchungen
        ]
        self.assertEqual(
            arten,
            [
                # Nach Symbol und Datum sortiert, wie Buchungen_Jahr der Mappe.
                ("US0000000001", "Kauf"),
                ("US0000000001", "Kauf"),
                ("US0000000001", "Dividende"),
                ("US0000000019", "Verkauf"),
                ("SOL", "Crypto Deposit"),
                ("SOL", "Crypto Deposit"),
            ],
        )
        self.assertEqual(
            [b["Symbol"] for b in self.buchungen],
            ["ALPH", "ALPH", "ALPH", "BETA", "SOL", "SOL"],
        )
        self.assertEqual(self.wv["US0000000001"]["Buchungen"], 3)
        self.assertEqual(self.wv["CH0000000013"]["Buchungen"], 0)

    def test_leere_felder_statt_null(self):
        """Swissquote schreibt 0.00, wo es keinen Wert gibt."""
        deposit = next(b for b in self.buchungen if b["Transaktionen"] == "Crypto Deposit")
        self.assertIsNone(deposit["Stueckpreis"])
        self.assertIsNone(deposit["Nettobetrag"])
        self.assertEqual(deposit["Anzahl"], Decimal("0.25"))
        dividende = next(b for b in self.buchungen if b["Transaktionen"] == "Dividende")
        self.assertIsNone(dividende["Stueckpreis"])
        self.assertEqual(dividende["Nettobetrag"], Decimal("3.00"))

    def test_wertschriften_mit_symbol_und_lesbarer_bezeichnung(self):
        self.assertEqual(self.wv["US0000000001"]["Symbol"], "ALPH")
        self.assertEqual(self.wv["SOL"]["Symbol"], "SOL")
        # Ohne Buchung im Jahr kennt nur die CSV das Symbol.
        self.assertEqual(self.wv["CH0000000013"]["Symbol"], "")
        # "Position in SOL" aus dem PDF wird durch den CSV-Namen ersetzt.
        self.assertEqual(self.wv["SOL"]["Bezeichnung"], "SOLANA")

    def test_wertschriften_nach_abschnitt_und_bezeichnung(self):
        ergebnis = pipeline.auswerten(
            beispieldaten.beispiel_csv(),
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )
        self.assertEqual(
            [z["Identifier"] for z in ergebnis["wertschriftenverzeichnis"]],
            ["US0000000001", "US0000000019", "CH0000000013", "SOL"],
        )

    def test_ohne_kontozinsen_und_ohne_folgeperiode(self):
        self.assertTrue(all(b["Identifier"] for b in self.buchungen))
        self.assertTrue(
            all(b["Datum"] <= date(2025, 12, 31) for b in self.buchungen)
        )

    def test_buchung_mit_neuer_wertschrift_erscheint_als_position(self):
        zeile = (
            "20-06-2025 00:00:00;800010;Dividende;DELT;DELTA PLC;GB0000000001;5;"
            "0.00;0.00;0;2.00;1.00;GBP"
        )
        rohdaten = beispieldaten.beispiel_csv() + (zeile + "\r\n").encode("latin-1")
        ergebnis = pipeline.auswerten(
            rohdaten,
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )
        wv = {z["Identifier"]: z for z in ergebnis["wertschriftenverzeichnis"]}
        self.assertEqual(wv["GB0000000001"]["Bezeichnung"], "DELTA PLC")
        self.assertEqual(wv["GB0000000001"]["Buchungen"], 1)
        # Steht in keinem PDF: Aktie oder Fonds ist aus der CSV nicht zu
        # erkennen, also sagt die Anwendung das, statt zu raten.
        self.assertEqual(
            wv["GB0000000001"]["Abschnitt"], pipeline.ABSCHNITT_UNBEKANNT
        )

    def test_abschnitt_wird_aus_der_buchung_abgeleitet(self):
        """Gekauft und wieder verkauft: die Position steht in keinem PDF."""
        zeilen = (
            "10-03-2025 10:00:00;800020;Kauf;DOT;POLKADOT;EX0X00DOT000;20;"
            "5.00;0.50;0;-100.50;1.00;USD",
            "10-09-2025 10:00:00;800021;Verkauf;DOT;POLKADOT;EX0X00DOT000;20;"
            "6.00;0.50;0;119.50;1.00;USD",
            "12-03-2025 10:00:00;800022;Kauf;GAMM;GAMMA ETP;CH0000000099;3;"
            "10.00;0.50;0;-30.50;1.00;CHF",
            "12-09-2025 10:00:00;800023;Verkauf;GAMM;GAMMA ETP;CH0000000099;3;"
            "11.00;0.50;0;32.50;1.00;CHF",
        )
        rohdaten = beispieldaten.beispiel_csv() + "".join(
            zeile + "\r\n" for zeile in zeilen
        ).encode("latin-1")
        ergebnis = pipeline.auswerten(
            rohdaten,
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )
        wv = {z["Identifier"]: z for z in ergebnis["wertschriftenverzeichnis"]}
        abgleich = {z["Identifier"]: z for z in ergebnis["abgleich_bestand"]}

        # Die Pseudo-ISIN verraet die Kryptowaehrung eindeutig.
        self.assertEqual(wv["DOT"]["Abschnitt"], "Kryptowährungen")
        self.assertEqual(abgleich["DOT"]["Abschnitt"], "Kryptowährungen")
        # Eine echte ISIN verraet den Abschnitt nicht.
        self.assertEqual(
            wv["CH0000000099"]["Abschnitt"], pipeline.ABSCHNITT_UNBEKANNT
        )
        self.assertEqual(
            abgleich["CH0000000099"]["Abschnitt"], pipeline.ABSCHNITT_UNBEKANNT
        )
        # Keine Zeile bleibt ohne Abschnitt und faellt aus der Gruppierung.
        self.assertTrue(all(z["Abschnitt"] for z in ergebnis["wertschriftenverzeichnis"]))
        # Gekauft und verkauft: der Abgleich geht trotzdem auf.
        self.assertEqual(abgleich["DOT"]["Status"], "OK")
        self.assertEqual(abgleich["CH0000000099"]["Status"], "OK")

    def test_abschnitt_aus_buchung_einzeln(self):
        self.assertEqual(
            pipeline.abschnitt_aus_buchung({"ISIN": "EX0X00SOL000"}),
            "Kryptowährungen",
        )
        self.assertEqual(
            pipeline.abschnitt_aus_buchung({"ISIN": "US0000000001"}),
            pipeline.ABSCHNITT_UNBEKANNT,
        )
        self.assertEqual(
            pipeline.abschnitt_aus_buchung({}), pipeline.ABSCHNITT_UNBEKANNT
        )


class TestFehlerfaelle(unittest.TestCase):
    def test_unbekannte_buchungsart_wird_gemeldet(self):
        csv_mit_luecke = beispieldaten.beispiel_csv().decode("latin-1").replace(
            "Dividende", "Neue Buchungsart", 1
        )
        ergebnis = pipeline.auswerten(
            csv_mit_luecke.encode("latin-1"),
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )
        checks = _als_dict(ergebnis["dq_checks"], "Test", "Ergebnis")
        self.assertEqual(checks["Regel für jede Buchungsart"], "Fehler")
        betroffene = _als_dict(ergebnis["dq_checks"], "Test", "Betroffene_Zeilen")
        self.assertEqual(betroffene["Regel für jede Buchungsart"], 1)

    def test_fehlende_transaktion_macht_den_abgleich_sichtbar(self):
        # Ein Kauf fehlt in der CSV: der Abgleich muss das melden.
        zeilen = [
            zeile
            for zeile in beispieldaten.CSV_ZEILEN
            if not zeile.startswith("12-03-2025")
        ]
        text = "\r\n".join((beispieldaten.CSV_KOPF,) + tuple(zeilen)) + "\r\n"
        ergebnis = pipeline.auswerten(
            text.encode("latin-1"),
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )
        alpha = next(
            zeile
            for zeile in ergebnis["abgleich_bestand"]
            if zeile["Identifier"] == "US0000000001"
        )
        self.assertEqual(alpha["Status"], "Fehler")
        self.assertEqual(alpha["Differenz"], Decimal(5))
        checks = _als_dict(ergebnis["dq_checks"], "Test", "Ergebnis")
        self.assertEqual(checks["Abgleich Bestand vs. Transaktionen"], "Fehler")

    def test_eigene_regeln_koennen_geladen_werden(self):
        regel_csv = (
            "Buchungsart;Kategorie;Faktor;Faktor_Menge;Zuordnung_Vorjahr\r\n"
            "Kauf;Bestandesänderung;1;1;0\r\n"
        ).encode("latin-1")
        regeln = pipeline.lies_regeln(regel_csv)
        self.assertEqual(len(regeln), 1)
        self.assertEqual(regeln[0]["Faktor_Menge"], Decimal(1))

    def test_regeln_round_trip(self):
        text = pipeline.regeln_als_csv(pipeline.standard_regeln())
        regeln = pipeline.lies_regeln(text.encode("utf-8"))
        self.assertEqual(len(regeln), len(pipeline.STANDARD_REGELN))
        self.assertEqual(regeln[0]["Buchungsart"], "Crypto Deposit")

    def test_leere_regeldatei_wird_gemeldet(self):
        with self.assertRaises(ValueError):
            pipeline.lies_regeln(b"Buchungsart;Kategorie\r\n")


if __name__ == "__main__":
    unittest.main()


class TestGebuehrenUndKontozinsen(unittest.TestCase):
    ZUSATZ = (
        # Im Januar belastet: gilt fuer das Vorjahr 2024, also nicht in der Periode.
        "08-01-2025 00:00:00;800030;Depotgebühren;;Depot;;0;0.00;0.00;0;-40.00;1.00;CHF",
        "04-07-2025 00:00:00;800031;Depotgebühren;;Depot;;0;0.00;0.00;0;-40.00;1.00;CHF",
        # Im Januar des Folgejahres belastet: gilt fuer 2025.
        "07-01-2026 00:00:00;800032;Depotgebühren;;Depot;;0;0.00;0.00;0;-42.50;1.00;CHF",
        "04-07-2025 00:00:00;800033;Depotgebühren;;Depot;;0;0.00;0.00;0;-3.00;1.00;USD",
        # Schuldzinsen am 1. Januar 2025 gehoeren zu 2024.
        "01-01-2025 00:00:00;800034;Zinsen auf Belastungen;;Konto USD 9999;;0;"
        "0.00;0.00;0;-1.10;1.00;USD",
        "01-07-2025 00:00:00;800035;Zinsen auf Belastungen;;Konto USD 9999;;0;"
        "0.00;0.00;0;-2.10;1.00;USD",
    )

    def setUp(self):
        rohdaten = beispieldaten.beispiel_csv() + "".join(
            zeile + "\r\n" for zeile in self.ZUSATZ
        ).encode("latin-1")
        self.ergebnis = pipeline.auswerten(
            rohdaten,
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )
        self.ohne_zusatz = pipeline.auswerten(
            beispieldaten.beispiel_csv(),
            beispieldaten.beispiel_anfangsbestand(),
            beispieldaten.beispiel_endbestand(),
        )

    def test_depotgebuehren_der_periode_mit_januar_regel(self):
        gebuehren = self.ergebnis["gebuehren"]
        self.assertEqual(
            [(g["Datum"], g["Zaehlt_zu"], g["Betrag"], g["Waehrung"]) for g in gebuehren],
            [
                # Aus den Beispieldaten.
                (date(2025, 2, 2), date(2025, 2, 2), Decimal("-9.00"), "CHF"),
                (date(2025, 7, 4), date(2025, 7, 4), Decimal("-40.00"), "CHF"),
                (date(2026, 1, 7), date(2025, 12, 31), Decimal("-42.50"), "CHF"),
                (date(2025, 7, 4), date(2025, 7, 4), Decimal("-3.00"), "USD"),
            ],
        )

    def test_boersengebuehren_nicht_in_der_liste(self):
        arten = {g["Transaktionen"] for g in self.ergebnis["gebuehren"]}
        self.assertEqual(arten, {"Depotgebühren"})

    def test_summe_je_waehrung(self):
        self.assertEqual(
            [(s["Waehrung"], s["Anzahl_Buchungen"], s["Summe"]) for s in self.ergebnis["gebuehren_summen"]],
            [("CHF", 3, Decimal("-91.50")), ("USD", 1, Decimal("-3.00"))],
        )

    def test_abgleich_bleibt_unveraendert(self):
        self.assertEqual(
            self.ergebnis["abgleich_bestand"], self.ohne_zusatz["abgleich_bestand"]
        )
        # Depotgebuehren bleiben fuer den Abgleich verworfen, wie in der Mappe.
        self.assertEqual(
            len(self.ergebnis["verworfene_transaktionen"]),
            len(self.ohne_zusatz["verworfene_transaktionen"]) + 4,
        )

    def test_kontozinsen_der_periode(self):
        zinsen = self.ergebnis["kontozinsen"]
        self.assertEqual(
            [(z["Transaktionen"], z["Zaehlt_zu"], z["Betrag"], z["Konto"]) for z in zinsen],
            [
                ("Zinsen auf Einlagen", date(2025, 12, 31), Decimal("1.2"), "Konto CHF"),
                # Monatserster: zaehlt laut Regel zum Vortag.
                ("Zinsen auf Belastungen", date(2025, 6, 30), Decimal("-2.10"), "Konto USD"),
            ],
        )

    def test_keine_kontoreferenz_in_den_kontozinsen(self):
        csv_text = pipeline.als_csv(self.ergebnis["kontozinsen"], pipeline.KONTOZINS_SPALTEN)
        self.assertNotIn("9999", csv_text)
