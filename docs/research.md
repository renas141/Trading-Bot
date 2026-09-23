# Erste Forschungsstrategie und Quartalsauswertung

`trend_breakout` ist eine bewusst einfache, austauschbare Hypothese. Sie wurde vor
der Auswertung festgelegt und nicht nachträglich auf die Ergebnisse optimiert.
Sie ist ausschließlich für BACKTEST wählbar; `no_trade` bleibt der Standard.

## Vorab festgelegte Regeln

Alle vier Bedingungen müssen gleichzeitig erfüllt sein:

| Faktor | Bedingung |
| --- | --- |
| Trend | Schlusskurs über SMA(50) und SMA(50) höher als bei der vorherigen Kerze. |
| Breakout | Schlusskurs über dem höchsten High der vorherigen 20 Kerzen. |
| Momentum | Schlusskurs höher als fünf Kerzen zuvor. |
| Volumen | Aktuelles Volumen mindestens 1,2-mal so groß wie der Durchschnitt der vorherigen 20 Kerzen; dieser muss positiv sein. |

Die aktuelle Kerze ist bei Breakout- und Volumenvergleich ausdrücklich nicht
Teil des Vergleichsfensters. Alle Kerzen sind abgeschlossen. Mindestens 51
Kerzen werden benötigt, sonst entsteht ein erklärtes HOLD-Signal.

ATR ist hier das einfache Mittel der letzten 14 True Ranges, inklusive Gaps,
nicht Wilders geglätteter ATR. Vorgeschlagener Stop: Schlusskurs minus 2 ATR.
Vorgeschlagenes Ziel: Schlusskurs plus zweimal den Abstand zum Stop. Der Stop
muss positiv sein. Diese Vorgaben werden an der nächsten Eröffnung durch die
Risk Engine erneut geprüft; die Strategie bestimmt weder Menge noch Hebel.

Der Confidence-Wert ist die Zahl erfüllter Bedingungen geteilt durch vier.
Er ist **keine geschätzte Gewinnwahrscheinlichkeit**. Jeder Faktor und der ATR
werden mit den verwendeten Werten in den Signalgründen dokumentiert. Das
Preisziel berücksichtigt keine garantierte Nettorendite; Gebühren können auch
einen am Preisziel geschlossenen Trade netto negativ machen.

## Daten und eingefrorenes Protokoll

Quelle ist die BTC/EUR-15m-Datei aus dem offiziellen Kraken-Archiv Q2/2026.
Der geprüfte Datensatz enthält 8.736 Kerzen ohne Lücken:

- Entwicklung: 01.04.2026 bis 01.06.2026, 5.856 Kerzen.
- Holdout: 01.06.2026 bis 01.07.2026, 2.880 Kerzen.
- Grenzen jeweils UTC, Ende exklusiv.

Für jeden Lauf werden ein neues Konto mit 1.000 EUR und eine neue
Strategieinstanz erzeugt. Der Holdout erhält die letzten 50 Entwicklungskerzen
als Warm-up. Dafür werden keine Trades ausgeführt und keine Positionen
übertragen. Die Strategie sieht pro Schritt nur die bis dahin bekannten Daten;
eine begrenzte Historienansicht verhindert versehentlichen Zugriff über ihren
aktuellen Index hinaus. Sie ist keine Sandbox für fremden Python-Code.

Zwei Kostenfälle sind vorab festgelegt:

| Fall | Gebühr je Seite | Slippage je Seite | Voller Spread |
| --- | ---: | ---: | ---: |
| base | 0,26 % | 5 Basispunkte | 10 Basispunkte |
| double_costs | 0,52 % | 10 Basispunkte | 20 Basispunkte |

Die Werte sind Forschungsannahmen, keine abgerufene aktuelle Kraken-Gebührenstufe.
Risikogrenzen bleiben bei den Projekt-Defaults: 1 % pro Trade, 3 % insgesamt,
3 % Tagesverlust, 10 % Drawdown, eine Position, 1x. Das Forschungsprogramm
verwendet dieses feste Preset und liest keine `.env`. Es handelt ausschließlich
simuliert und verwendet keine Zugangsdaten.

`protocol.json` wird **vor der ersten Performanceberechnung** geschrieben und
enthält Parameter, Datenprüfsumme, Python-Version und SHA-256-Prüfsummen des
ausgeführten Anwendungscodes. `results.json` verweist auf dieses Protokoll.
Alle vier Ergebnisse werden veröffentlicht; das Programm sucht oder aktiviert
keinen Gewinner.

## Ausführung

Im Projektordner mit aktivierter Umgebung:

```bash
python -m backtesting.research \
  --dataset data/datasets/kraken_btc_eur_15m_2026q2 \
  --split-at 2026-06-01T00:00:00Z \
  --output data/research/trend_breakout_2026q2_reproduction
```

Nach erneuter Paketinstallation ist derselbe Befehl als `trading-research`
verfügbar. Der Ausgabeordner muss neu sein. Er enthält das Protokoll, einen
Markdown-Bericht, vollständige JSON-Ergebnisse und `research.sqlite3` mit
Orders, Trades, Signalen, Risikoentscheidungen und Equity je Session.

Für einen einzelnen Backtest ohne Entwicklungs-/Holdout-Trennung:

```bash
TRADING_MODE=BACKTEST LOG_LEVEL=WARNING python main.py \
  --dataset data/datasets/kraken_btc_eur_15m_2026q2 --strategy trend_breakout
```

## Erstes Ergebnis: Hypothese nicht bestätigt

Die unveränderte Auswertung liegt lokal unter
`data/research/trend_breakout_2026q2_v1/`.

| Zeitraum | Kosten | Trades | Netto EUR | Rendite | Gebühren EUR |
| --- | --- | ---: | ---: | ---: | ---: |
| Entwicklung | base | 24 | −100,00 | −10,00 % | 89,88 |
| Entwicklung | double_costs | 18 | −100,00 | −10,00 % | 80,04 |
| Holdout | base | 16 | −100,00 | −10,00 % | 55,42 |
| Holdout | double_costs | 13 | −100,00 | −10,00 % | 61,66 |

Die Werte sind gerundet. Das Restkapital liegt jeweils knapp über 900 EUR.
Das Drawdown-Budget ist praktisch ausgeschöpft; weitere Einstiege scheitern
danach an der aus dem Restbudget berechneten Mindestpositionsgröße. Die
Simulation verliert nicht den gesamten Kontowert. Unterschiedliche Trade-Zahlen
und Gebühren ergeben sich auch aus den kostenabhängig berechneten Positionsgrößen.

Unter diesen Annahmen liefert diese Version keinen positiven Befund. Die
Strategie wird nicht automatisch für PAPER aktiviert. Parameter wurden nach
Einsicht in den Holdout nicht geändert. Der Juni-Holdout ist nun als gesehen
zu behandeln; eine neue Hypothese benötigt einen anderen unabhängigen Test.

Die Auswertung deckt nur ein Quartal, ein Paar und einen Timeframe ab. Sie
enthält keine Tick-Rekonstruktion, keinen Walk-Forward und keine Aussage über
zukünftige Rendite. Die [Diagnose von Kosten und einzelnen Trades](diagnostics.md)
ist abgeschlossen. Sie bestätigt die Hypothese nicht; eine neue Hypothese wurde
noch nicht festgelegt oder getestet.
