# Swissquote-Steuerauszug

Eine clientseitige Anwendung, die zwei Swissquote-Bestands-PDFs und die
Transaktions-CSV im Browser gegeneinander prüft: **Anfangsbestand plus
Transaktionen der Periode muss den Endbestand ergeben.** Die Dateien werden
nicht an ein Backend übertragen.

Die Auswertung ist eine Portierung der Power-Query-Mappe
`PQ_Swissquote_Steuerauszug.xlsx` und liefert bewusst dieselben Zahlen, damit
sich beide Wege gegeneinander verifizieren lassen.

## Lokal starten

1. Öffne diesen Ordner im Terminal.
2. Starte einen Webserver:

   ```bash
   python3 -m http.server 8000
   ```

3. Öffne <http://localhost:8000> im Browser.
4. Lade die drei Dateien:
   - das PDF «Portfolio-Wertentwicklung» mit dem **Anfangsbestand**
   - das PDF «Portfolio-Wertentwicklung» mit dem **Endbestand**
   - die **Transaktions-CSV**

Die Auswertung startet, sobald alle drei Dateien geladen sind. Die Stichtage
liest die Anwendung aus dem Titel der PDFs; ein Steuerjahr musst du nirgends
einstellen. Die CSV muss alle Buchungen zwischen den beiden Stichtagen
enthalten, inklusive der Nachbuchungen im Januar des Folgejahres. Lade sie
also nicht nur für das Kalenderjahr herunter.

Beim ersten Laden werden PyScript und das Paket `pypdf` aus dem Internet
bezogen. Die PDF-Verarbeitung braucht eine Textschicht; eingescannte PDFs
werden nicht unterstützt.

## Was die Anwendung rechnet

| Schritt | Entspricht der Abfrage |
|---|---|
| CSV einlesen, Stornos und ignorierte Buchungsarten filtern | `transaktionen` |
| Regeln je Buchungsart | `tbl_regeln` |
| Bestände je PDF samt Stichtag | `Übersicht_Anfangsb`, `Übersicht_Endb` |
| Kategorie, Zuordnungsdatum und Periode je Buchung | `Übersicht_Transaktionen` |
| Anfangs- und Endbestand je Position | `Gesamtübers_Bestand` |
| Mengenänderung aus den Buchungen der Periode | `Transaktionen_proSymbol` |
| Differenz und Status je Position | `Abgleich_Bestand` |
| Prüfungen | `DQ_Checks` |

### Regeln je Buchungsart

`Faktor` wirkt auf den Betrag, `Faktor_Menge` auf die Stückzahl im Abgleich
(0 heisst: die Buchung ändert keine Menge). `Zuordnung_Vorjahr = 1` bedeutet,
dass eine Buchung am Monatsersten zum Vortag zählt — so landen zum Beispiel
die am 1. Januar gutgeschriebenen Zinsen in der richtigen Periode.

Die 16 Standardregeln sind eingebaut. Du kannst sie herunterladen, in Excel
ergänzen und wieder hochladen; eine Buchungsart ohne Regel meldet der
Prüfschritt «Regel für jede Buchungsart».

### Perioden

Die Zuordnung ergibt sich aus den beiden Stichtagen, nicht aus einer
Jahreszahl im Code:

- bis und mit Stichtag Anfang → **Vorperiode**
- danach bis und mit Stichtag Ende → **Periode**
- später → **Folgeperiode**

In den Abgleich gehen nur Buchungen der **Periode** ein.

### Abweichungen von der Mappe

- **Kontokorrent-Salden** werden aus dem Abschnitt «Liquidität» gelesen, die
  Mappe erfasst sie heute nicht. Sie stehen **nicht** im Abgleich, weil
  Zahlungen, Forex- und Kartenbuchungen herausgefiltert werden und die
  Differenz sonst immer von null abweichen würde. Für das
  Wertschriftenverzeichnis sind sie über «Bestände herunterladen» verfügbar.
- Zwei zusätzliche Prüfungen: verworfene Zeilen ohne Währung (als Hinweis,
  weil der Filter auch nicht stornierte Corporate Actions trifft) und nicht
  lesbare Datumswerte.

### Was die Anwendung nicht liefert

Valoren-Nummern, offizielle Steuerwerte, Bruttoerträge in CHF zum Tageskurs,
die Zuordnung zu Kolonne A oder B und die DA-1-Prüfung. Der Abgleich ist eine
Prüfhilfe und keine steuerliche Beurteilung.

## Entwicklung

Die Rechenlogik steht in `pipeline.py` und kennt kein DOM; `main.py` enthält
nur Ein- und Ausgabe im Browser. Dadurch laufen die Tests ohne Browser:

```bash
python3 -m unittest discover -s tests -t .
```

Beispieldateien zum Ausprobieren erzeugen (synthetisch, ohne echte Kontodaten):

```bash
python3 tests/erzeuge_beispieldateien.py
```

Die Dateien landen in `beispiel/` und sind von `.gitignore` erfasst.

## Datenschutz

CSV-, PDF- und Excel-Dateien gehören nicht in Git oder GitHub und sind über
`.gitignore` ausgeschlossen. Das gilt ausdrücklich auch für die
Power-Query-Mappe: sie enthält die geladenen Abfrageergebnisse und damit echte
Bestände, Transaktionen und Salden sowie die Kontonummer in den
Parameter-Vorgaben.

Die Verarbeitung erfolgt lokal im Browser; aus dem Internet geladen werden nur
PyScript und `pypdf`. Die Kontoreferenz aus dem Liquiditäts-Abschnitt des PDF
wird beim Parsen übersprungen und nicht exportiert.
