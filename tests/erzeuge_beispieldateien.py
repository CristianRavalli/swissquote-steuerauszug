"""Erzeugt synthetische Beispieldateien zum Ausprobieren der Anwendung.

Schreibt den Layout-Text aus tests/beispieldaten.py als echtes PDF, mit
Courier und ohne externe Pakete, dazu die Beispiel-CSV. Die Dateien enthalten
keine echten Kontodaten und landen in beispiel/ (von .gitignore erfasst).

    python3 tests/erzeuge_beispieldateien.py
"""
import os
import sys

SEITENBREITE = 1400
SEITENHOEHE = 900
SCHRIFTGROESSE = 6
ZEILENHOEHE = 9
RAND_LINKS = 15
RAND_OBEN = 30


def _escape(text):
    roh = text.encode("latin-1", errors="replace")
    roh = roh.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return roh


def _inhaltsstrom(zeilen):
    teile = [b"BT", b"/F1 %d Tf" % SCHRIFTGROESSE, b"%d TL" % ZEILENHOEHE]
    teile.append(b"1 0 0 1 %d %d Tm" % (RAND_LINKS, SEITENHOEHE - RAND_OBEN))
    for zeile in zeilen:
        teile.append(b"(" + _escape(zeile) + b") Tj")
        teile.append(b"T*")
    teile.append(b"ET")
    return b"\n".join(teile)


def schreibe_pdf(text, ziel):
    seiten = [
        [zeile for zeile in block.split("\n")]
        for block in text.split("\n\n")
        if block.strip()
    ]

    objekte = []  # (nummer, bytes)
    anzahl_seiten = len(seiten)
    seiten_ids = [4 + 2 * i for i in range(anzahl_seiten)]

    objekte.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    kids = b" ".join(b"%d 0 R" % nummer for nummer in seiten_ids)
    objekte.append(
        (
            2,
            b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % anzahl_seiten,
        )
    )
    objekte.append(
        (
            3,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
            b"/Encoding /WinAnsiEncoding >>",
        )
    )

    for index, zeilen in enumerate(seiten):
        seiten_id = seiten_ids[index]
        inhalt_id = seiten_id + 1
        strom = _inhaltsstrom(zeilen)
        objekte.append(
            (
                seiten_id,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
                % (SEITENBREITE, SEITENHOEHE, inhalt_id),
            )
        )
        objekte.append(
            (
                inhalt_id,
                b"<< /Length %d >>\nstream\n" % len(strom) + strom + b"\nendstream",
            )
        )

    objekte.sort(key=lambda eintrag: eintrag[0])
    ausgabe = bytearray(b"%PDF-1.4\n")
    versatz = {}
    for nummer, koerper in objekte:
        versatz[nummer] = len(ausgabe)
        ausgabe += b"%d 0 obj\n" % nummer + koerper + b"\nendobj\n"

    xref_start = len(ausgabe)
    hoechste = max(versatz) + 1
    ausgabe += b"xref\n0 %d\n" % hoechste
    ausgabe += b"0000000000 65535 f \n"
    for nummer in range(1, hoechste):
        if nummer in versatz:
            ausgabe += b"%010d 00000 n \n" % versatz[nummer]
        else:
            ausgabe += b"0000000000 65535 f \n"
    ausgabe += (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (hoechste, xref_start)
    )

    with open(ziel, "wb") as datei:
        datei.write(bytes(ausgabe))
    return anzahl_seiten


def main():
    projekt = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, projekt)
    from tests import beispieldaten

    ziel = os.path.join(projekt, "beispiel")
    os.makedirs(ziel, exist_ok=True)

    seiten_a = schreibe_pdf(
        beispieldaten.beispiel_anfangsbestand(),
        os.path.join(ziel, "beispiel-anfang.pdf"),
    )
    seiten_e = schreibe_pdf(
        beispieldaten.beispiel_endbestand(),
        os.path.join(ziel, "beispiel-ende.pdf"),
    )
    with open(os.path.join(ziel, "beispiel-transaktionen.csv"), "wb") as datei:
        datei.write(beispieldaten.beispiel_csv())

    print(f"beispiel/beispiel-anfang.pdf        {seiten_a} Seiten")
    print(f"beispiel/beispiel-ende.pdf          {seiten_e} Seiten")
    print("beispiel/beispiel-transaktionen.csv  geschrieben")


if __name__ == "__main__":
    main()
