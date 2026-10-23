# Swissquote-Steuerauszug

Eine clientseitige PyScript-Anwendung, um Swissquote-Transaktions-CSV-Dateien
und Bestands-PDFs im Browser zu prüfen. Die Dateien werden nicht an ein Backend
übertragen.

## Lokal starten

1. Öffne diesen Ordner in VS Code.
2. Starte im Terminal:

   ```bash
   python3 -m http.server 8000
   ```

3. Öffne <http://localhost:8000> im Browser.
4. Lade Anfangs- und Endbestands-PDF sowie die Transaktions-CSV hoch.

Beim ersten Laden werden PyScript und die Python-Pakete aus dem Internet
geladen. Die PDF-Verarbeitung unterstützt Text-PDFs, keine eingescannten PDFs.

## Was die Anwendung aktuell zeigt

- Bestände aus Anfangs- und End-PDF, zusammengeführt nach ISIN bzw. Währung
- erkannte Bestandsänderungen
- Ertragsbuchungen und Summen nach Kategorie und Währung
- separate Prüfliste für Transaktionen vom 1. bis einschließlich 13. Januar
  2026; ausgewählte Ertragsbuchungen fließen in die Summen für 2025 ein

Die Kategorisierung ist eine Prüfhilfe und keine automatische steuerliche
Beurteilung. Prüfe die Zuordnung der Buchungen anhand deiner Unterlagen.

## Datenschutz

CSV- und PDF-Dateien gehören nicht in Git oder GitHub. Sie werden deshalb über
`.gitignore` vom Repository ausgeschlossen. Die Verarbeitung der Dateien
erfolgt lokal im Browser; PyScript und benötigte Pakete werden beim Laden der
Seite aus dem Internet bezogen.
