# Historische BTC/EUR-Daten

Diese Stufe bereitet **Spot-Marktdaten** auf. Sie verbindet kein Kraken-Konto und
sendet keine Orders. Spot-Candles ersetzen später keine Derivate-, Funding- oder
Liquidationsdaten.

## Öffentlicher Download

Im Projektordner mit aktivierter `.venv`:

```bash
python -m app.market_data.cli download --bars 480 --timeframe 15m --output data/datasets/btc_eur_15m
```

Nach erneuter Paketinstallation ist alternativ `trading-data` verfügbar.
Unterstützte Intervalle: `1m`, `5m`, `15m`, `1h`, `4h`. `--bars` erlaubt 1 bis 719
abgeschlossene Intervalle. Das Ende wird vor der Anfrage auf die letzte
abgeschlossene Intervallgrenze in UTC gesetzt; der Anfang ergibt sich aus der
gewünschten Kerzenzahl. Ein neuer Download verwendet ein neues Zeitfenster.
Reproduzierbare Auswertungen verwenden deshalb den bereits gespeicherten Datensatz.

Kraken liefert höchstens 720 aktuelle Einträge, inklusive der noch offenen letzten
Kerze. Ältere Daten können mit diesem Endpunkt auch über `since` nicht abgerufen
werden. Der Adapter entfernt den letzten Eintrag immer und prüft zusätzlich die
Schlusszeit. Quelle: [Kraken OHLC API](https://docs.kraken.com/api-reference/market-data/get-ohlc-data).

Eine Anfrage verwendet ausschließlich GET, keine Anmeldung und keine Schlüssel.
Zeitlimit: 15 Sekunden pro Versuch; maximal drei Versuche bei Netzfehlern, HTTP 429
oder ausgewählten Serverfehlern. Weiterleitungen werden abgelehnt. Antworten sind
auf 2 MB begrenzt. Es gibt keine automatische Dauerschleife.

## Was gespeichert wird

```text
data/datasets/btc_eur_15m/
  source.raw       Unveränderte öffentliche Antwort bzw. eingelesene Archiv-CSV
  candles.csv      Normalisierte OHLCV-Daten mit Dezimalwerten und UTC-Zeitstempeln
  quality.json     Abdeckung, Lücken, Fehler, Zahl der Kerzen ohne Volumen
  manifest.json    Herkunft, Zeitraum, Formatversion und SHA-256-Prüfsummen
```

Der Zeitraum ist `[start, end)`: Start inklusive, Ende exklusiv. Candle-Zeitstempel
bezeichnen den Beginn eines Intervalls. Preise sind EUR pro BTC, Volumen ist BTC.
VWAP und Trade-Anzahl aus der API werden nicht mit dem Volumen verwechselt.

Bestehende Ausgabeordner werden nie überschrieben. Das Manifest entsteht zuletzt;
ein unterbrochener Schreibvorgang ohne Manifest ist kein verwendbarer Datensatz.
Der gesamte Ordner `data/` bleibt von Git ausgeschlossen.

## Qualität und Wiederverwendung

```bash
python -m app.market_data.cli verify data/datasets/btc_eur_15m
TRADING_MODE=BACKTEST python main.py --dataset data/datasets/btc_eur_15m
```

`verify` prüft die Dateiprüfsummen und berechnet die Abdeckung erneut. Der
`--dataset`-Start prüft außerdem Symbol und Timeframe gegen die Bot-Konfiguration.
Alle Prüfungen sind offline möglich.

Abgelehnt werden ungültige OHLC-Werte, negative oder nicht endliche Werte,
Duplikate, falsche Reihenfolge, Intervallüberlappungen, falsche Intervallgrenzen,
gemischte Märkte/Intervalle, offene Kerzen und fehlende erwartete Intervalle.
Lücken am Anfang und Ende des angeforderten Zeitraums zählen ebenfalls.
Kerzen mit Volumen null werden gezählt, aber allein deshalb nicht verworfen.

Lückenhafte Downloads werden zur Untersuchung gespeichert, erhalten jedoch
`ready: false`. Der Download endet dann mit Rückgabecode `2`; `verify`,
`--dataset` und Splits lehnen solche Datensätze ab. Rückgabecode `1` bezeichnet
einen Abruf-, Format- oder Dateifehler; `0` bedeutet erfolgreiche Prüfung.
Es werden keine Kurse ergänzt, Daten sortiert oder Duplikate still entfernt.

Prüfsummen erkennen Dateiänderungen gegenüber dem lokalen Manifest. Sie sind
keine digitale Signatur des Datenanbieters. Ein qualitativ vollständiger Datensatz
garantiert auch keine ökonomische Plausibilität oder Eignung einer Strategie.

Der ältere `--csv`-Start prüft Werte und innere Zeitlücken, hat aber ohne Manifest
keinen Nachweis über die ursprünglich angeforderte Anfangs-/Endabdeckung.
Für wiederholbare Auswertungen ist `--dataset` vorzuziehen.

## Längere Historien aus offiziellen Archiven

Ein einzelner BTC/EUR-Zeitraum kann nun direkt aus einem offiziellen Quartals-ZIP
geladen werden, ohne alle Märkte herunterzuladen:

```bash
python -m app.market_data.cli download-archive --quarter 2026Q2 --timeframe 15m \
  --output data/datasets/kraken_btc_eur_15m_2026q2
```

Freigegebene Quartale: `2026Q1`, `2026Q2`. Der Abruf liest das ZIP-Verzeichnis und
die benötigte BTC/EUR-Datei über HTTP-Bytebereiche. Budget: insgesamt 20 MB,
entpackte CSV maximal 100 MB. Ignoriert der Server die Bereiche oder ändert sich
die ETag, bricht der Abruf ab. Es gibt keinen stillen Voll-Download.
Die CSV wird im Speicher gelesen; fremde ZIP-Pfade werden nicht ins Dateisystem
entpackt. Herkunft, ETag, Mitgliedsname und CRC32 stehen im Manifest. Die Prüfung
umfasst das gewählte ZIP-Mitglied, nicht die Prüfsumme des gesamten Archivs.

Der erste Abruf von Q2/2026 übertrug 792.775 Bytes aus einem Archiv mit
537.866.903 Bytes. Er lieferte 8.736 vollständige 15m-Kerzen vom 01.04.2026
00:00 UTC bis 01.07.2026 00:00 UTC (Ende exklusiv), ohne fehlende Intervalle.

Kraken stellt umfangreiche OHLCVT-Archive bereit. Die CSV-Dateien haben keinen
Header und enthalten `timestamp,open,high,low,close,volume,trades`; der Zeitstempel
ist Unix-Zeit in Sekunden. Intervalle ohne Trades können fehlen.
Quelle und Downloadlinks: [Kraken historische OHLCVT-Daten](https://support.kraken.com/de/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data).

Die großen Gesamtarchive werden weiterhin nicht automatisch heruntergeladen. Eine bereits
entpackte BTC/EUR-Datei mit dem ursprünglichen Namen `XBTEUR_15.csv` kann so
eingelesen werden; die Daten müssen den gewählten Beispielzeitraum tatsächlich abdecken:

```bash
python -m app.market_data.cli import-kraken \
  --csv data/archive/XBTEUR_15.csv --timeframe 15m \
  --start 2025-01-01T00:00:00Z --end 2026-01-01T00:00:00Z \
  --output data/datasets/btc_eur_2025
```

Der Name muss zum BTC/EUR-Markt und Intervall passen (`XBTEUR_1.csv`,
`XBTEUR_5.csv`, `XBTEUR_15.csv`, `XBTEUR_60.csv`, `XBTEUR_240.csv`). Die Datei
enthält selbst keine Marktkennung; andere Märkte dürfen deshalb nicht umbenannt
werden. Das Manifest kennzeichnet die Herkunft als vom Nutzer gelieferte Datei,
deren Echtheit nicht unabhängig verifiziert wurde. Aktuelles Importlimit: 100 MB
je CSV. ZIP-Dateien werden nicht automatisch entpackt.

Bei fehlenden Intervallen bleibt die Qualitätsprüfung streng. Eine spätere
Behandlung von Phasen ohne Handel muss als eigene, dokumentierte Regel entwickelt
werden; diese Version setzt dafür keine synthetischen Kerzen ein.

## Entwicklungsdaten und spätere Testdaten trennen

Für einen Datensatz, der den folgenden Zeitpunkt umfasst:

```bash
python -m app.market_data.cli split data/datasets/btc_eur_2025 \
  --at 2025-10-01T00:00:00Z --output data/splits/btc_eur_2025
```

`development.csv` enthält die früheren Kerzen, `holdout.csv` die späteren.
`split.json` dokumentiert Trennzeitpunkt, Prüfsummen und Ausgangsdatensatz.
Die Teilmengen müssen nichtleer und überschneidungsfrei sein. Es wird nie zufällig
gemischt. Auch der Trennzeitpunkt muss auf einer Intervallgrenze liegen.

Dieser Befehl erledigt nur die Datentrennung. Die eigentliche Auswertung einer
festen Hypothese beschreibt [research.md](research.md). Sie nutzt vorherige
Entwicklungsdaten nur als indikatorischen Warm-up und übernimmt keine Positionen
über die Grenze. Holdout-Ergebnisse dürfen nicht zum Nachoptimieren verwendet
werden; ein vollständiger Walk-Forward-Ablauf fehlt noch.

## Bereits geprüfter erster Datensatz

Lokal liegt `data/datasets/kraken_btc_eur_15m_initial`: 480 Kerzen vom
17.09.2026 05:15 UTC bis 22.09.2026 05:15 UTC (Ende exklusiv), ohne Lücken.
Die spätere Tagesperiode wird in `data/splits/kraken_btc_eur_15m_initial` getrennt:
384 Kerzen für die Entwicklung, 96 für den Holdout, Grenze 21.09.2026 05:15 UTC.
Dieser kurze Datensatz dient ausschließlich dem Funktionstest der Pipeline.
