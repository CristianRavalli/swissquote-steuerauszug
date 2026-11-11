"""Browser-Schicht: Dateien einlesen, pipeline aufrufen, Tabellen zeichnen.

Die Auswertungslogik steht in pipeline.py und kennt kein DOM. Diese Datei
enthaelt deshalb keine Rechenregeln, nur Ein- und Ausgabe.
"""

from decimal import Decimal

from js import Blob, URL, Uint8Array, document
from pyscript import when

import pipeline

VORSCHAU_ZEILEN = 50

zustand = {
    "anfang_text": None,
    "anfang_name": None,
    "ende_text": None,
    "ende_name": None,
    "csv_rohdaten": None,
    "csv_name": None,
    "regeln": pipeline.standard_regeln(),
    "ergebnis": None,
}

ABGLEICH_SPALTEN = (
    "Identifier",
    "Produkt_Name",
    "Abschnitt",
    "Anfangsbestand",
    "Endbestand",
    "Änderung_Bestand",
    "Veraenderung_Transaktionen",
    "Anzahl_Transaktionen",
    "Differenz",
    "Status",
)

BESTAND_SPALTEN = (
    "Schluessel",
    "Anzahl",
    "Produkt_Name",
    "Abschnitt",
    "Stichtag",
    "Stichtag_Bezeichnung",
)

TRANSAKTIONEN_SPALTEN = (
    "Datum",
    "Zuordnungsdatum",
    "Periode",
    "Transaktionen",
    "Kategorie",
    "Symbol",
    "Name",
    "ISIN",
    "Schluessel",
    "Anzahl",
    "Anzahl_mitVorzeichen",
    "Faktor",
    "Faktor_Menge",
    "Nettobetrag",
    "Kosten",
    "Waehrung",
    "q_Kategorisierung",
)

TRANSAKTIONEN_ANZEIGE = (
    "Datum",
    "Zuordnungsdatum",
    "Periode",
    "Transaktionen",
    "Kategorie",
    "Symbol",
    "Schluessel",
    "Anzahl",
    "Nettobetrag",
    "Waehrung",
    "q_Kategorisierung",
)

DQ_SPALTEN = ("Test", "Betroffene_Zeilen", "Ergebnis")

VERWORFEN_ANZEIGE = (
    "CSV_Zeile",
    "Grund",
    "Datum",
    "Transaktionen",
    "Symbol",
    "Name",
    "Anzahl",
    "Nettobetrag",
    "Waehrung",
)

VERWORFEN_SPALTEN = (
    "CSV_Zeile",
    "Grund",
    "Datum",
    "Auftrag",
    "Transaktionen",
    "Symbol",
    "Name",
    "ISIN",
    "Anzahl",
    "Nettobetrag",
    "Waehrung",
)

REGEL_ANZEIGE = pipeline.REGEL_SPALTEN


# --- Ausgabe -----------------------------------------------------------------


def setze_status(text, art="info"):
    status = document.querySelector("#status")
    status.textContent = text
    status.dataset.art = art


def _zelle(wert):
    zelle = document.createElement("td")
    if isinstance(wert, Decimal):
        zelle.textContent = pipeline.formatiere_zahl(wert)
        zelle.className = "zahl"
    elif isinstance(wert, int) and not isinstance(wert, bool):
        zelle.textContent = str(wert)
        zelle.className = "zahl"
    elif wert is None:
        zelle.textContent = ""
    else:
        zelle.textContent = str(wert)
    return zelle


def rendere_tabelle(selector, zeilen, spalten, grenze=None, leer_selector=None):
    koerper = document.querySelector(selector)
    koerper.replaceChildren()

    anzuzeigen = zeilen if grenze is None else zeilen[:grenze]
    for daten in anzuzeigen:
        reihe = document.createElement("tr")
        status = daten.get("Status") or daten.get("Ergebnis")
        if status in ("Fehler", "Hinweis"):
            reihe.dataset.status = status
        for spalte in spalten:
            zelle = _zelle(daten.get(spalte))
            if spalte == "Ergebnis" and status:
                zelle.className = "ergebnis-" + str(status)
            reihe.appendChild(zelle)
        koerper.appendChild(reihe)

    if leer_selector is not None:
        leer = document.querySelector(leer_selector)
        if zeilen:
            leer.hidden = True
        else:
            leer.hidden = False
    return len(anzuzeigen)


def rendere_regeln():
    rendere_tabelle("#regeln", zustand["regeln"], REGEL_ANZEIGE)


def rendere_stichtage(ergebnis):
    liste = document.querySelector("#stichtage")
    liste.replaceChildren()

    if ergebnis is None:
        eintrag = document.createElement("li")
        eintrag.textContent = "Noch keine PDFs geladen."
        liste.appendChild(eintrag)
        return

    anfang = ergebnis["stichtag_anfang"]
    ende = ergebnis["stichtag_ende"]
    hinweise = ergebnis["hinweise"]
    posten = (
        ("Stichtag Anfang", anfang.strftime("%d.%m.%Y")),
        ("Stichtag Ende", ende.strftime("%d.%m.%Y")),
        ("Positionen Anfang", str(len(ergebnis["anfangsbestand"]))),
        ("Positionen Ende", str(len(ergebnis["endbestand"]))),
        ("Buchungen in der CSV", str(hinweise["gelesen"])),
        ("davon ausgewertet", str(len(ergebnis["uebersicht_transaktionen"]))),
    )
    for titel, wert in posten:
        eintrag = document.createElement("li")
        starke = document.createElement("strong")
        starke.textContent = wert
        eintrag.appendChild(starke)
        eintrag.appendChild(document.createTextNode(titel))
        liste.appendChild(eintrag)


def setze_downloads_aktiv(aktiv):
    for selector in (
        "#download-abgleich",
        "#download-bestand",
        "#download-transaktionen",
        "#download-verworfen",
        "#download-wv",
        "#download-wv-buchungen",
    ):
        document.querySelector(selector).disabled = not aktiv


# --- Auswertung --------------------------------------------------------------


def alles_geladen():
    return (
        zustand["anfang_text"] is not None
        and zustand["ende_text"] is not None
        and zustand["csv_rohdaten"] is not None
    )


def werte_aus():
    if not alles_geladen():
        fehlend = []
        if zustand["anfang_text"] is None:
            fehlend.append("Bestands-PDF Anfang")
        if zustand["ende_text"] is None:
            fehlend.append("Bestands-PDF Ende")
        if zustand["csv_rohdaten"] is None:
            fehlend.append("Transaktions-CSV")
        setze_status("Es fehlt noch: " + ", ".join(fehlend) + ".")
        return

    setze_status("Auswertung läuft …")
    try:
        ergebnis = pipeline.auswerten(
            zustand["csv_rohdaten"],
            zustand["anfang_text"],
            zustand["ende_text"],
            zustand["regeln"],
        )
    except ValueError as fehler:
        zustand["ergebnis"] = None
        setze_downloads_aktiv(False)
        setze_status(f"Auswertung nicht möglich: {fehler}", "fehler")
        return

    zustand["ergebnis"] = ergebnis
    rendere_stichtage(ergebnis)
    rendere_tabelle("#dq-checks", ergebnis["dq_checks"], DQ_SPALTEN, None, "#dq-leer")

    abgleich = sorted(
        ergebnis["abgleich_bestand"],
        key=lambda zeile: (zeile["Status"] == "OK", zeile["Identifier"]),
    )
    rendere_tabelle("#abgleich", abgleich, ABGLEICH_SPALTEN, None, "#abgleich-leer")
    angezeigt = rendere_tabelle(
        "#transaktionen",
        ergebnis["uebersicht_transaktionen"],
        TRANSAKTIONEN_ANZEIGE,
        VORSCHAU_ZEILEN,
        "#transaktionen-leer",
    )
    rendere_tabelle(
        "#verworfen",
        ergebnis["verworfene_transaktionen"],
        VERWORFEN_ANZEIGE,
        None,
        "#verworfen-leer",
    )
    rendere_tabelle(
        "#wv", ergebnis["wertschriftenverzeichnis"], pipeline.WV_SPALTEN, None, "#wv-leer"
    )
    rendere_tabelle(
        "#wv-buchungen",
        ergebnis["wv_buchungen"],
        pipeline.WV_BUCHUNG_SPALTEN,
        None,
        "#wv-buchungen-leer",
    )
    setze_downloads_aktiv(True)

    fehler = [zeile for zeile in ergebnis["dq_checks"] if zeile["Ergebnis"] == "Fehler"]
    hinweise = [
        zeile for zeile in ergebnis["dq_checks"] if zeile["Ergebnis"] == "Hinweis"
    ]
    gesamt = len(ergebnis["uebersicht_transaktionen"])
    rest = max(gesamt - angezeigt, 0)
    meldung = (
        f"Stichtage {ergebnis['stichtag_anfang'].strftime('%d.%m.%Y')} bis "
        f"{ergebnis['stichtag_ende'].strftime('%d.%m.%Y')}. "
        f"{len(ergebnis['abgleich_bestand'])} Positionen abgeglichen, "
        f"{gesamt} Buchungen ausgewertet"
    )
    if rest:
        meldung += f" (angezeigt: die ersten {angezeigt})"
    meldung += ". "
    def _liste(zeilen):
        return ", ".join(
            f"{zeile['Test']} ({zeile['Betroffene_Zeilen']})" for zeile in zeilen
        )

    if fehler:
        meldung += "Nicht bestanden: " + _liste(fehler) + "."
        if hinweise:
            meldung += " Hinweis: " + _liste(hinweise) + "."
        setze_status(meldung, "fehler")
    elif hinweise:
        meldung += "Keine Fehler. Hinweis: " + _liste(hinweise) + "."
        setze_status(meldung)
    else:
        meldung += "Alle Prüfungen bestanden."
        setze_status(meldung)


# --- Dateieingaben -----------------------------------------------------------


async def _rohdaten(datei):
    puffer = await datei.arrayBuffer()
    return bytes(Uint8Array.new(puffer))


async def lade_pdf(event, schluessel, bezeichnung):
    datei = event.target.files.item(0)
    if datei is None:
        return

    setze_status(f"Lese {bezeichnung}: {datei.name} …")
    try:
        rohdaten = await _rohdaten(datei)
        text = pipeline.extrahiere_pdf_text(rohdaten)
        # Fruehe Rueckmeldung: Stichtag und Positionen pruefen, bevor die
        # ganze Kette laeuft.
        positionen, stichtag = pipeline.lies_bestand(text, bezeichnung)
    except ValueError as fehler:
        zustand[schluessel + "_text"] = None
        setze_downloads_aktiv(False)
        setze_status(f"{datei.name}: {fehler}", "fehler")
        return
    except Exception as fehler:  # pypdf wirft eigene Fehlertypen
        zustand[schluessel + "_text"] = None
        setze_downloads_aktiv(False)
        setze_status(
            f"{datei.name} konnte nicht als PDF gelesen werden: {fehler}", "fehler"
        )
        return

    zustand[schluessel + "_text"] = text
    zustand[schluessel + "_name"] = datei.name
    setze_status(
        f"{bezeichnung} per {stichtag.strftime('%d.%m.%Y')}: "
        f"{len(positionen)} Positionen erkannt."
    )
    werte_aus()


@when("change", "#anfang-pdf")
async def lade_anfang(event):
    await lade_pdf(event, "anfang", pipeline.ANFANGSBESTAND)


@when("change", "#ende-pdf")
async def lade_ende(event):
    await lade_pdf(event, "ende", pipeline.ENDBESTAND)


@when("change", "#csv-datei")
async def lade_csv(event):
    datei = event.target.files.item(0)
    if datei is None:
        return

    setze_status(f"Lese {datei.name} …")
    try:
        rohdaten = await _rohdaten(datei)
        pipeline.lies_transaktionen(rohdaten)
    except ValueError as fehler:
        zustand["csv_rohdaten"] = None
        setze_downloads_aktiv(False)
        setze_status(f"{datei.name}: {fehler}", "fehler")
        return

    zustand["csv_rohdaten"] = rohdaten
    zustand["csv_name"] = datei.name
    werte_aus()


@when("change", "#regeln-datei")
async def lade_regeln(event):
    datei = event.target.files.item(0)
    if datei is None:
        return

    try:
        rohdaten = await _rohdaten(datei)
        regeln = pipeline.lies_regeln(rohdaten)
    except ValueError as fehler:
        setze_status(f"{datei.name}: {fehler}", "fehler")
        return

    zustand["regeln"] = regeln
    rendere_regeln()
    setze_status(f"{len(regeln)} Regeln aus {datei.name} geladen.")
    werte_aus()


@when("click", "#regeln-zuruecksetzen")
def setze_regeln_zurueck(event):
    zustand["regeln"] = pipeline.standard_regeln()
    document.querySelector("#regeln-datei").value = ""
    rendere_regeln()
    setze_status("Regeln auf den Standard zurückgesetzt.")
    werte_aus()


# --- Downloads ---------------------------------------------------------------


def lade_herunter(inhalt, dateiname):
    blob = Blob.new([inhalt], {"type": "text/csv;charset=utf-8"})
    adresse = URL.createObjectURL(blob)
    verweis = document.createElement("a")
    verweis.href = adresse
    verweis.download = dateiname
    document.body.appendChild(verweis)
    verweis.click()
    verweis.remove()
    URL.revokeObjectURL(adresse)


def _jahr():
    ergebnis = zustand["ergebnis"]
    if ergebnis is None:
        return "auswertung"
    return str(ergebnis["stichtag_ende"].year)


@when("click", "#download-abgleich")
def download_abgleich(event):
    ergebnis = zustand["ergebnis"]
    if ergebnis is None:
        return
    lade_herunter(
        pipeline.als_csv(ergebnis["abgleich_bestand"], ABGLEICH_SPALTEN),
        f"abgleich-bestand-{_jahr()}.csv",
    )


@when("click", "#download-bestand")
def download_bestand(event):
    ergebnis = zustand["ergebnis"]
    if ergebnis is None:
        return
    zeilen = list(ergebnis["anfangsbestand"]) + list(ergebnis["endbestand"])
    lade_herunter(
        pipeline.als_csv(zeilen, BESTAND_SPALTEN),
        f"bestaende-{_jahr()}.csv",
    )


@when("click", "#download-transaktionen")
def download_transaktionen(event):
    ergebnis = zustand["ergebnis"]
    if ergebnis is None:
        return
    lade_herunter(
        pipeline.als_csv(
            ergebnis["uebersicht_transaktionen"], TRANSAKTIONEN_SPALTEN
        ),
        f"transaktionen-{_jahr()}.csv",
    )


@when("click", "#download-verworfen")
def download_verworfen(event):
    ergebnis = zustand["ergebnis"]
    if ergebnis is None:
        return
    lade_herunter(
        pipeline.als_csv(ergebnis["verworfene_transaktionen"], VERWORFEN_SPALTEN),
        f"verworfene-buchungen-{_jahr()}.csv",
    )


@when("click", "#download-wv")
def download_wv(event):
    ergebnis = zustand["ergebnis"]
    if ergebnis is None:
        return
    lade_herunter(
        pipeline.als_csv(ergebnis["wertschriftenverzeichnis"], pipeline.WV_SPALTEN),
        f"wertschriften-{_jahr()}.csv",
    )


@when("click", "#download-wv-buchungen")
def download_wv_buchungen(event):
    ergebnis = zustand["ergebnis"]
    if ergebnis is None:
        return
    lade_herunter(
        pipeline.als_csv(ergebnis["wv_buchungen"], pipeline.WV_BUCHUNG_SPALTEN),
        f"wertschriften-buchungen-{_jahr()}.csv",
    )


@when("click", "#download-regeln")
def download_regeln(event):
    lade_herunter(pipeline.regeln_als_csv(zustand["regeln"]), "tbl_regeln.csv")


# --- Start -------------------------------------------------------------------

rendere_regeln()
rendere_stichtage(None)
setze_status(
    "Bereit. Lade die beiden Bestands-PDFs und die Transaktions-CSV; "
    "die Auswertung startet automatisch."
)
