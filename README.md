# ETF Freistellungsauftragsrechner

Eine kleine App zur optimalen Ausnutzung des Freistellungsauftrags aus einer Trade-Republic-Transaktions-CSV. In Trade Republic kann die .csv direkt
heruntergeladen werden. Alternativ kann eine manuelle csv-Datei erstellt werden. 

## Funktionen

- Import einer Trade-Republic-Transaktionsdatei im CSV-Format
- Filterung der Transaktionen nach einer eingegebenen ISIN bzw. einem Symbol
- Berechnung des verbleibenden ETF-Bestands
- Berechnung der gesamten Anschaffungskosten und des durchschnittlichen Kaufpreises
- Berechnung von Verkaufswert und aktuellem Gewinn auf Basis des eingegebenen Kurses
- Schätzung der zu verkaufenden Anteile zur Nutzung des verbleibenden Freistellungsauftrags
- Anzeige der verbleibenden Kauf-Lots zur Nachvollziehbarkeit der FIFO-Berechnung

## Voraussetzungen

- Python 3.9 oder neuer (empfohlen)
- `pandas`
- `streamlit`
- Eine passende Trade-Republic-Transaktions-CSV (eine Beispieldatei ist angehängt)

## Installation

1. Repository bzw. Projektordner herunterladen und im Terminal öffnen.

2. Benötigte Pakete installieren:

   ```bash
   pip install pandas streamlit
   ```

## Anwendung starten

Wechsle im Terminal in den Ordner, in dem sich die Python-Datei befindet. Wenn die Datei `main.py` heißt, starte die Anwendung mit:

```bash
streamlit run main.py
```

Streamlit öffnet die Anwendung normalerweise im Browser. Falls nicht, zeigt das Terminal eine lokale URL an, die du im Browser öffnen kannst.

## Verwendung

1. **Transaktions-CSV hochladen:** Wähle in der Anwendung deine Trade-Republic-Transaktionsdatei aus.
2. **Aktuellen Kurs eingeben:** Trage den aktuellen Kurs eines ETF-Anteils in Euro ein.
3. **Verbleibenden Freistellungsauftrag eingeben:** Gib den Betrag in Euro ein, der noch genutzt werden soll.
4. **ISIN eingeben:** Trage die ISIN ein, nach der die Transaktionen gefiltert werden sollen. 
5. **Ergebnisse prüfen:** Die Anwendung zeigt die gefilterten Transaktionen, den aktuellen Bestand, die Anschaffungskosten, den durchschnittlichen Kaufpreis, den aktuellen Gewinn und eine Schätzung der für den Freistellungsauftrag zu verkaufenden Anteile an.

## Erwartete CSV-Spalten

Die Anwendung erwartet in der CSV mindestens die folgenden Spaltennamen:

| Spalte | Verwendung |
|---|---|
| `type` | Transaktionstyp, z. B. `BUY`, `MERGER` oder `SELL` |
| `symbol` | Symbol bzw. ISIN, anhand derer gefiltert wird |
| `shares` | Anzahl der Anteile |
| `price` | Preis je Anteil |

Die Spaltennamen müssen so vorhanden sein, wie sie im Code angegeben sind. Zusätzliche Spalten werden beim Einlesen nicht weiterverwendet. Die Anwendung setzt außerdem voraus, dass die Werte in `shares` und `price` numerisch eingelesen werden können.

## Berechnungslogik

### Bestand und Anschaffungskosten

Der Code berücksichtigt Kauf- (`BUY`), Fusions-/Umtausch- (`MERGER`) und Verkaufsbuchungen (`SELL`). Verkäufe werden anhand der Reihenfolge der Transaktionen mit früheren Kaufpositionen verrechnet. Anschließend berechnet die Anwendung aus den verbleibenden Kauf-Lots:

- **Anteile:** Summe der verbleibenden Anteile
- **Anschaffungskosten:** Summe aus verbleibenden Anteilen multipliziert mit dem jeweiligen Kaufpreis
- **Durchschnittlicher Kaufpreis:** Anschaffungskosten geteilt durch die verbleibenden Anteile

### Aktueller Gewinn

Der aktuelle Verkaufswert wird als Bestand multipliziert mit dem eingegebenen aktuellen Kurs berechnet. Der angezeigte Gewinn ergibt sich aus Verkaufswert minus den ermittelten Anschaffungskosten.

### Freistellungsauftrag

Für die Schätzung des erforderlichen Verkaufs verwendet der Code standardmäßig eine Teilfreistellung von **30 %**. Er leitet daraus den benötigten Gewinn vor Teilfreistellung ab und ermittelt unter Verwendung der FIFO-Reihenfolge, wie viele Anteile dafür verkauft werden müssten.

Die Berechnung ist lediglich eine Schätzung. Also Benutzung auf eigene Gefahr.

## Hinweise und Einschränkungen

- Die Ergebnisse hängen von der Vollständigkeit und korrekten Struktur der CSV-Datei ab.
- Der eingegebene Kurs ist eine manuelle Eingabe und wird nicht automatisch von einer Börse abgerufen.
- Die Anwendung dient der Orientierung und ersetzt keine Steuerberatung.
- Prüfe die Ergebnisse und die verwendeten Annahmen vor einer tatsächlichen Verkaufsentscheidung.
- Die im Code verwendeten Transaktionstypen und die Reihenfolge der CSV-Daten beeinflussen das Ergebnis.

## Projektstruktur

Beispiel für eine minimale Projektstruktur:

```text
projektordner/
├── main.py
└── README.md
```

## Fehlerbehebung

**Die Anwendung startet nicht**
- Prüfe, ob du im richtigen Ordner bist.
- Prüfe, ob die Datei tatsächlich `main.py` heißt.
- Installiere die Abhängigkeiten mit `pip install pandas streamlit`.

**Es werden keine Transaktionen gefunden**
- Prüfe, ob die CSV die Spalten `type`, `symbol`, `shares` und `price` enthält.
- Prüfe, ob die eingegebene ISIN mit den Werten in der Spalte `symbol` übereinstimmt.
- Prüfe, ob die Datei Transaktionen für die gewünschte Position enthält.

**Fehler beim Einlesen der CSV**
- Prüfe, ob die Datei ein gültiges CSV-Format hat und die erforderlichen Spalten numerische Werte für `shares` und `price` enthalten.
