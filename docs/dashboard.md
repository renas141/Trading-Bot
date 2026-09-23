# Lokale Forschungsübersicht

Das Dashboard zeigt abgeschlossene Forschungsberichte, Kontoverläufe, Trades und
Signalentscheidungen. Es startet keine Simulation und führt keine Orders aus.

## Starten

Im Projektordner nach Installation der aktuellen Version:

```bash
uv sync --frozen --no-editable
.venv/bin/trading-dashboard
```

Alternativ direkt aus dem Projekt:

```bash
.venv/bin/python -m dashboard.server
```

Danach [http://127.0.0.1:8765](http://127.0.0.1:8765) im Browser öffnen.
Mit Strg+C im Terminal beenden. Es wird kein Autostart eingerichtet. Ist der
Port belegt, mit `--port 8766` einen anderen lokalen Port wählen.

Die Oberfläche benötigt nur die bestehende Python-Umgebung und einen Browser.
Keine zusätzlichen Pakete, externen Schriften, CDN-Aufrufe oder Telemetrie.
Die deutschsprachige Oberfläche passt sich an schmale Bildschirme an. Der
Server bleibt ausschließlich auf diesem Rechner erreichbar.

## Ansichten

- **Übersicht:** Versuch, Abschnitt, Kostenannahme und Variante auswählen.
  Endkapital, Nettoergebnis, Trades, maximaler Rückgang, Kontoverlauf,
  Ablehnungsgründe und gespeicherte Benchmarks beziehen sich auf genau dieses Konto.
- **Trades:** Gewinne und Verluste filtern, blättern und Ein- und Ausstiege mit
  Gebühren, Stop, Kursziel und Originalbegründungen öffnen.
- **Entscheidungen:** Kaufsignale oder Abwarten anzeigen, nach Freigabe filtern
  und Bedingungen sowie die Entscheidung der Risikoprüfung nachvollziehen.
- **Bericht herunterladen:** Den gespeicherten Markdown-Bericht des Versuchs
  herunterladen. Es wird keine neue Auswertung erzeugt.

Q1-Abschnitte sowie Q2-Entwicklung und ehemaliger Holdout bleiben getrennt.
Kontowerte werden nicht zusammengerechnet. Kaufen-und-Halten und Nicht-Handeln
erscheinen nur, wenn der Versuch sie gespeichert hat. Fehlende Werte werden
nicht als Null ausgegeben. Null-Trade-Läufe behalten eine ausdrückliche Leeransicht.

Für den Chart bleiben je Zeitreihenblock Minimum und Maximum sowie Anfang und
Ende erhalten. Kennzahlen stammen aus dem vollständigen gespeicherten Ergebnis,
nicht aus der verdichteten Grafik. Die X-Achse zeigt Zeit; die Werte sind keine
Tickdaten. Geldbeträge werden für die Anzeige gerundet.

Unvollständige oder widersprüchliche Artefakte erscheinen als nicht verfügbar
oder mit Fehlermeldung. „Neu laden“ aktualisiert abgeschlossene Versuche;
es findet kein automatischer Marktdatenabruf statt.

## Lesender Zugriff

Quelle ist `data/research/`. Unterstützt werden `fixed-hypothesis-v1` und
`net-reward-segmented-v2` sowie `slow-timeframe-gated-v1`. Letzteres zeigt
Jahreskonten mit der richtigen Kerzendauer und dem jeweiligen Holdout-Status.
Ein gebundener Datenprüfungsbericht (`blocked.json`) erscheint als gesperrter
Versuch mit herunterladbarem Bericht, ohne erfundene Kennzahlen oder leere
Kontokurve. Vorherige abgeschlossene Versuche bleiben auswählbar.
Eine andere lokale Quelle lässt sich mit
`--research-root /absoluter/pfad` angeben.

SQLite-Datenbanken werden mit `mode=ro` und `query_only=ON` geöffnet, ohne
Repository-Migrationen oder Broker-Import. Abgeschlossene BACKTEST-Sessions
werden mit Ergebnissen und Endkapital abgeglichen. Ergebnisdateien müssen auf
die richtige Protokoll-Prüfsumme verweisen. Dies ersetzt keine unabhängige
Prüfung der ursprünglichen Marktquelle.

Schreibmethoden werden zurückgewiesen. Browserparameter enthalten keine
Dateipfade; Symlinks außerhalb des Quellenordners werden abgelehnt. Der Server
bindet fest an `127.0.0.1` und weist fremde Host-/Origin-Angaben zurück. Er ist
für lokale Nutzung gedacht, nicht für öffentliches Hosting oder mehrere Nutzer.

Paper-Session-Verwaltung, neue Strategien und Handelsfreigaben gehören nicht zu
dieser Oberfläche. LIVE bleibt technisch gesperrt.
