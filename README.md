# Trading-Bot

Modulare Python-Grundlage für die lokale Entwicklung eines algorithmischen
Krypto-Trading-Systems. Erste Stufe: Bitcoin, historische Daten und Simulation.
Es gibt **keine echten Orders, keine laufenden Softwarekosten und keine
implementierte profitable Handelsstrategie**.

## Aktueller Umfang

- Python 3.13, moderne Typangaben und unveränderliche Datenmodelle für `Candle`,
  `Signal`, `Order`, `Position`, `Trade`.
- Zentrale, validierte Konfiguration; `.env` optional, Umgebungsvariablen haben Vorrang.
- Abstrakte Schnittstellen für Exchange, Strategie, RiskManager, Broker und Execution.
- SQLite mit Repository-Schicht, Transaktionen, Fremdschlüsseln und Schema-Version.
- Erklärbare Signale mit Confidence, Strategie-Version und Ablehnungsgründen.
- PaperBroker mit virtuellem EUR-Guthaben, vollständig finanzierten LONG-Positionen,
  Gebühren, Spread, Slippage, Preis-/Mengenrundung und realisiertem Netto-P&L.
- Getrennter BACKTEST/PAPER-Derivatekern für einen linearen BTC/USD-Perpetual:
  LONG/SHORT, Funding, Margin, Trade-/Mark-Preis, Liquidation und dynamisch 1x–10x.
- Stopbasierte Positionsgrößen, Gesamt-/Tagesrisiko, Drawdown-Sperre und Kill Switch.
- Chronologischer Backtest mit Einstieg frühestens am nächsten Kerzenbeginn,
  Stop Loss, Take Profit, konservativer Behandlung mehrdeutiger Kerzen und Kennzahlen.
- Öffentlicher Kraken-Spot-Download und Import offizieller OHLCVT-CSV-Dateien,
- wiederaufnehmbare öffentliche Kraken-Perpetual-Kostenmessung für Spread,
  geschätzte Slippage, Funding und Datenalter mit Mindestabdeckung vor jeder
  Kostenkalibrierung,
  inklusive Herkunft, SHA-256-Prüfsummen und Qualitätsbericht.
- Prüfung auf Lücken und unvollständige Kerzen sowie chronologische Trennung
  in Entwicklungsdaten und spätere Holdout-Daten.
- Optional wählbare Forschungsstrategie `trend_breakout` mit Trend-, Breakout-,
  Momentum- und Volumenfilter sowie ATR-basierten Stop-/Zielvorschlägen.
- Festes Forschungsprotokoll mit Holdout-Auswertung und verdoppelten Kosten.
- Zweite Forschungshypothese mit Nettoziel-/Stop-Risiko-Prüfung am Einstieg,
  dokumentierter Datenlücke und getrennten Auswertungen zusammenhängender Abschnitte.
- Vergleichswerte für Nicht-Handeln und Kaufen-und-Halten mit denselben Kosten.
- Lokale, lesende Forschungsübersicht mit Kontoverlauf, Trade-Journal,
  Signalentscheidungen, Filtern und gespeicherten Berichten.
- Rotierende lokale Logs und Unit-/Integrationstests ohne externe Dienste.

Der PAPER-Start verwendet weiterhin eine Policy, die jeden Trade ablehnt. BACKTEST
verwendet die neue Stop-Risikoprüfung, aber die ausgelieferte `NoTradeStrategy`
liefert ausschließlich HOLD. Der normale Start eröffnet deshalb keine Position.
Synthetische Testsignale prüfen die Handelsmechanik. `trend_breakout` muss für
BACKTEST ausdrücklich gewählt werden; PAPER akzeptiert diese Forschungsstrategie nicht.
Die erste Quartalsauswertung fiel negativ aus, siehe [Forschung](docs/research.md).
Auch die [zweite Hypothese mit Nettoziel-Filter](docs/net-reward-research.md)
lieferte keinen positiven Nettobefund. Eine dokumentierte Datenlücke in Q1
erforderte zwei getrennte Auswertungsabschnitte. Der Filter reduzierte Verluste,
ließ bei normalen Kosten aber nur sechs Trades und bei doppelten Kosten keinen zu.

## Architektur

```text
app/
  config/          Settings, .env-Loader und RiskLimits
  exchange/        ExchangeAdapter, öffentlicher Kraken-OHLC-Lesezugriff
  market_data/     Candle, Download/Import, Qualitätsprüfung, Datensätze und Splits
  indicators/     Decimal-Mittelwert und einfacher ATR
  strategies/     Strategy, Signal, NoTradeStrategy, TrendBreakoutStrategy, Registry
  regime/         RegimeDetector und mögliche Marktregime
  risk/           StopRiskManager, Nettoziel-Filter, Risikozustand, Kill Switch
  execution/      Broker/Execution, OrderManager, PaperBroker, Kostenmodell, Order
  portfolio/      Position, Trade, PortfolioSnapshot
  database/       SQLite-Repository und Schema
  derivatives/    Perpetual-Kontrakt, Margin, Funding, Liquidation und Hebelrisiko
  cli.py          Zusammensetzen und Starten der Komponenten
  logging_config.py
backtesting/      Ausführung, Kennzahlen, Benchmarks, Forschung und Trade-Diagnose
dashboard/        Lokaler Webserver, lesende Forschungsabfragen und Oberfläche
tests/            Offline-Tests der Kernkomponenten
data/             Lokale CSVs und SQLite-Dateien, von Git ausgeschlossen
logs/             Lokale Logs, von Git ausgeschlossen
main.py           Kleiner CLI-Einstieg, keine Handelslogik
```

```text
Historische Candles → Strategy → Signal mit Gründen
                                  ↓
                           OrderManager
                                  ↓
                       zentrale Risk-Prüfung
                                  ↓ nur bei Freigabe
                            PaperBroker
                                  ↓
                      Portfolio + SQLite-Journal
```

Strategien importieren keine Kraken- oder Broker-Implementierung. Der
ExchangeAdapter liefert kanonische Marktdaten. Seine aktuelle Schnittstelle
hat bewusst keine Order-Funktion; die Datenmodule lesen ausschließlich öffentliche
Spot- und Futures-Daten. Neue Coins und Exchanges können später über Modelle und Adapter
ergänzt werden; die aktuelle Konfiguration ist auf `BTC/EUR` begrenzt.

Geldbeträge verwenden `Decimal`; SQLite speichert sie als Dezimalzeichenketten.
Zeitstempel müssen eine Zeitzone enthalten; Logs verwenden UTC. Candle-Zeitstempel
bezeichnen den Beginn des Intervalls, Signale dessen Schluss.

SQLite wird über die Python-Standardbibliothek und eine klar getrennte
Repository-Klasse angesprochen. Ein ORM ist für dieses kleine Schema noch nicht
notwendig. Position und Entry-Order sowie Exit-Order und Trade werden jeweils
atomar gespeichert; fehlgeschlagene Datenbankoperationen ändern kein Broker-Guthaben.
Die Schema-Version ist `3`. Versionen `1` und `2` werden in einer Transaktion
um fehlende Ergebnis-/Paper-Checkpoint-Tabellen ergänzt; vorhandene Sessions bleiben erhalten. Unbekannte
Versionen werden abgelehnt.

## Einrichtung

Voraussetzung: **Python 3.13**, Referenzversion `3.13.15` in `.python-version`.
Python 3.9, das auf macOS teilweise vorinstalliert ist, reicht nicht aus.
Alle Befehle im vorhandenen Projektordner ausführen.

Mit `uv` (legt `.venv` an und nutzt `uv.lock`):

```bash
uv sync --frozen --no-editable
source .venv/bin/activate
```

Alternativ mit Python und pip:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Es gibt keine zusätzlichen Laufzeit- oder Testabhängigkeiten. Die Installation
benötigt einmalig das festgelegte Build-Werkzeug `setuptools==80.9.0`; danach
arbeiten PAPER-Start, Tests und lokaler Replay ohne Netzverbindung.
Nur der ausdrücklich aufgerufene Daten-Download benötigt Internetzugang.
Aus dem Projektordner funktioniert `python main.py` auch ohne Paketinstallation.
Dieser Aufruf verwendet unmittelbar den aktuellen Quellcode. Der installierte
`trading-bot`-Befehl verwendet eine Paketkopie; nach Codeänderungen die Installation
erneut ausführen (`uv sync --frozen --no-editable --reinstall-package modular-crypto-trading-bot`
oder `python -m pip install .`). Die reguläre Installation vermeidet zusätzliche
Import-Hooks und funktioniert unabhängig vom Arbeitsverzeichnis.

Optional die Beispielkonfiguration kopieren:

```bash
cp .env.example .env
```

Die `.env` unterstützt einfache `KEY=VALUE`-Zeilen, vollständige Kommentarzeilen
und optional umschließende Anführungszeichen. Keine Shell-Ausführung, Expansion,
mehrzeiligen Werte oder Inline-Kommentare. Boolesche Werte: `true` / `false`.
Relative Daten-/Logpfade beziehen sich auf das aktuelle Arbeitsverzeichnis.

## Start und Tests

```bash
python main.py
# nach Paketinstallation alternativ:
trading-bot

python -m unittest discover -s tests -v
```

Der PAPER-Start legt eine SQLite-Datei unter `data/trading.sqlite3` und Logs unter
`logs/bot.log` an. Er erstellt eine Session mit 1.000 EUR virtuellem Kapital und
Anfangs-Equity und beendet sie mit `STOPPED`. Es läuft noch kein Hintergrunddienst.
Jeder Start erzeugt eine neue, unabhängige Session; eine bestehende Position wird
noch nicht aus der Datenbank fortgesetzt.

Historische Daten müssen die Spalten `timestamp,open,high,low,close,volume`
enthalten. Preise sind in EUR, Volumen in BTC. Beispiel des Formats mit **rein
synthetischen Testwerten, nicht echten historischen Kursen**:

```csv
timestamp,open,high,low,close,volume
2024-01-01T00:00:00Z,40000,40200,39800,40100,12.5
2024-01-01T00:15:00Z,40100,40300,40000,40200,10.2
```

Eine passende Datei z. B. unter `data/btc_eur_15m.csv` ablegen:

```bash
TRADING_MODE=BACKTEST python main.py --csv data/btc_eur_15m.csv
```

Der Import lehnt ungültige Preise, fehlende Zeitzonen, doppelte,
überlappende und unsortierte Candles ab. Vor dem Replay werden zusätzlich
Zeitlücken, falsche Intervallgrenzen und noch nicht abgeschlossene Kerzen abgelehnt.
Der Backtest speichert Signale, Risikoentscheidungen, Orders, Trades, Equity und
Kennzahlen samt Kosten-/Risikoparametern. Die Standardstrategie liefert HOLD und
somit keine Trades; undefinierte Kennzahlen werden als `null` ausgegeben.
Ausführungsregeln und Grenzen: [docs/simulation.md](docs/simulation.md).

Die erste Forschungsstrategie ausdrücklich im Backtest auswählen:

```bash
TRADING_MODE=BACKTEST LOG_LEVEL=WARNING python main.py \
  --dataset data/datasets/kraken_btc_eur_15m_2026q2 --strategy trend_breakout
```

Dieser Einzelaufruf verwendet den gesamten gewählten Datensatz. Für eine
vordefinierte Entwicklungs-/Holdout-Trennung stattdessen das Forschungsprotokoll
aus [docs/research.md](docs/research.md) verwenden. Es findet keine Parametersuche statt.

## Historische Kraken-Daten

Die vollständige Anleitung steht in [docs/market-data.md](docs/market-data.md).
Ein erster öffentlicher Download mit 480 abgeschlossenen BTC/EUR-Kerzen (15m,
fünf Tage) und anschließendem geprüften Replay:

```bash
python -m app.market_data.cli download --bars 480 --timeframe 15m --output data/datasets/btc_eur_15m
python -m app.market_data.cli verify data/datasets/btc_eur_15m
TRADING_MODE=BACKTEST python main.py --dataset data/datasets/btc_eur_15m
```

Der Ausgabeordner muss neu sein. Die Kraken-OHLC-API liefert höchstens 720
Einträge inklusive der noch offenen letzten Kerze; diese wird ausgeschlossen.
Für längere Zeiträume unterstützt `import-kraken` lokale offizielle Archiv-CSVs.
Ein kurzer Download prüft die Datenpipeline, ist keine ausreichende Grundlage
für Strategie- oder Profitabilitätsaussagen.

## Modi und Sicherheitsprinzipien

| Modus | Aktueller Stand |
| --- | --- |
| BACKTEST | Lokale Spot- und Perpetual-Simulation, keine realen Orders. |
| PAPER | Virtuelles Konto und Broker-Grundlage; Derivate nicht als Strategie aktiviert. |
| LIVE | Technisch gesperrt, nicht implementiert. |

- `TRADING_MODE=LIVE` **oder** `ENABLE_LIVE_TRADING=true` verhindert den Start.
  Es gibt keinen Konfigurationsschalter, der echte Orders freischaltet.
- API-Zugangsdaten werden nicht benötigt oder gelesen. Selbst gesetzte
  Kraken-Zugangsdaten aktivieren keine private Verbindung oder Orderfunktion.
  Der separate Download nutzt ausschließlich einen öffentlichen GET-Endpunkt.
- Keine Zugangsdaten im Code, in Logs oder Git. `.env`, lokale Datenbanken und
  Logs sind ausgeschlossen. Spätere Secrets ausschließlich über Environment/.env.
- Es werden keine Schlüssel erzeugt und keine Withdrawal-Rechte benötigt.
- Der `OrderManager` fragt vor einem Entry den zentralen `RiskManager`.
  Confidence allein kann keine Sicherheitsprüfung umgehen. Ein Stop ist erforderlich.
- Der PaperBroker prüft jede Freigabe erneut gegen die Stop-Risikoprüfung und den
  aktuellen Portfoliozustand. Ein Exit bleibt auch bei aktivem Kill Switch zulässig.
  `KILL_SWITCH` wird beim Start geladen; `broker.trip_kill_switch()` sperrt weitere
  Einstiege während einer Session. Eine UI dafür ist noch nicht vorhanden.
- Die Spot-Ausführung bleibt vollständig finanziert und 1x. Der getrennte
  Derivate-Backtest erlaubt dynamisch 1x bis maximal 10x. Er wählt nach der
  risikobasierten Positionsgröße den kleinsten nötigen Hebel und verlangt einen
  zusätzlichen Abstand zwischen Stop und Liquidation. Kurslücken können den
  geplanten Stop-Verlust trotzdem überschreiten. Gebühren, ganzer Spread und
  zusätzliche Slippage sind getrennte Annahmen; Risiko und Broker belasten je
  Ausführung denselben halben Spread plus dieselbe nachteilige Slippage.
- Python-Modulgrenzen sind keine Sandbox für fremden Strategiecode. Der Broker
  ist eine interne Schnittstelle, kein öffentlich zugänglicher Order-Endpunkt.

Spot-Kosten, Mindestwert und Preis-/Mengenschritte sind frei gewählte
Simulationsannahmen. Der Perpetual-Forschungsblock dokumentiert seine zeitgebundenen
Kraken-Annahmen und Quellen separat.
`cash` ist verfügbares Guthaben. Equity bewertet zusätzlich offene Positionen zum
angenommenen Netto-Verkaufserlös inklusive Ausführungskosten. Es gibt noch kein
Orderbuch- oder Teilfüllungsmodell. Funding, Margin und Liquidation sind im
separaten Perpetual-Replay vorhanden, noch nicht im normalen Spot-PaperBroker.

## Bewusst noch nicht implementiert

- Private Exchange-Anbindung, echte Orders und API-Secrets.
- Dauerhafter Derivate-Paperfeed; LONG/SHORT und Hebel sind derzeit nur lokal simuliert.
- Validierte profitable Strategien, kalibrierte Scores, Multi-Timeframe-Auswertung
  und konkrete Regime-Erkennung.
- Swing-basierte Stop-Ermittlung, Trailing, Break-even und Teilverkäufe.
  Die Forschungsstrategie schlägt ATR-basierte Stops vor; die Risk Engine prüft sie.
- Tickgenaue Backtest-Fills, Sharpe und Walk-Forward. Eine einfache zeitlich
  getrennte Holdout-Auswertung ist implementiert, noch keine breite Validierung.
- WebSockets, historisch vollständige Funding-, Orderbook- und Open-Interest-Daten.
  Eine begrenzte aktuelle [Perpetual-Kostenbeobachtung](docs/perpetual-observer.md)
  ist vorhanden, ersetzt diese Historie aber nicht.
- Dauerbetrieb, Wiederaufnahme bestehender Portfolios und parallele Handelsprozesse.
- Machine Learning, LLM-Entscheidungen und externe kostenpflichtige Dienste.

Die [lokale Forschungsübersicht](docs/dashboard.md) wird aus dem Projektordner mit
`.venv/bin/python -m dashboard.server` gestartet und unter
[127.0.0.1:8765](http://127.0.0.1:8765) geöffnet. Sie benötigt keine zusätzlichen
Pakete und zeigt abgeschlossene Forschungsdaten. Sie ist kein Handels-Terminal.
Die Datenbank trennt Sessions, Signale samt Strategie-Version/Risikogründen,
Orders mit Entry-/Exit-Gründen, Positionen, Trades, Equity und Backtest-Ergebnisse.
Die Perpetual-Studien erscheinen als abgeschlossene Berichtskarten; ihr
In-Memory-Replay besitzt derzeit noch kein interaktives SQLite-Trade-Journal.

## Nächste drei Entwicklungsschritte

Die [Trade- und Kostendiagnose](docs/diagnostics.md) ist abgeschlossen: Im Juni
waren die ausgeführten Trades bereits vor Kosten negativ; auch erreichte
Preisziele konnten nach Kosten Verlust bedeuten. Alle 71 Trades sind zerlegt,
die ursprünglichen Parameter und Forschungsartefakte unverändert.

Die zweite Hypothese einschließlich Kaufen-und-Halten- und Cash-Vergleich ist
ebenfalls abgeschlossen und negativ. Q1 und Q2 gelten jetzt als gesehen.

Die lokale Forschungsübersicht ist ebenfalls verfügbar; Forschungsdateien
werden dabei ausschließlich gelesen.

Die neue [Perpetual- und Hebelforschung](docs/perpetual-research-2026-09-23.md)
enthält den 1x–10x-Derivatekern, zwei eingefrorene Entwicklungsstufen und den
einmaligen 2025-Holdout. Der ausgewählte Long-only-Kandidat war 2023/2024 positiv,
scheiterte 2025 aber mit −1,91 % normal und −3,44 % im Stress. Er wurde deshalb
nicht für PAPER oder LIVE freigegeben. Zwei danach festgelegte Gewinnschutzregeln
verbesserten 2025 deutlich, blieben im Stress aber negativ; auch daraus wurde kein
Kandidat ausgewählt. Ein fester 10-Tage-Ausstieg verbesserte den 2025-Stressfall
anschließend von −34,40 USD auf −17,50 USD, bestand aber ebenfalls nicht. Ein
Momentum-Ausstieg und eine eintägige Wiedereinstiegspause waren jahrübergreifend
instabil. Auch daraus wurde kein Kandidat ausgewählt. Der Replay unterstützt nun
echte stündliche Funding-Reihen; fehlende Stunden werden abgelehnt. Für 2023–2025
bleiben konservative Funding-Sensitivitäten nötig, weil der öffentliche
Analytics-Abruf dort keine vollständige Historie lieferte. 2026-Kursdaten wurden
für diese Forschungsfolge weiterhin nicht ausgewertet. Zwei strukturell andere
Trendfolge-Varianten mit unbegrenztem Gewinnziel und ATR-Trailing wurden ebenfalls
vorab festgelegt. Der einfache Donchian-Ansatz erhöhte die Zahl der Trades und war
2023/2024 positiv, scheiterte 2025 aber mit −24,92 USD normal und −35,84 USD im
Stress. Die Parametersuche auf den gesehenen Jahren ist damit beendet.

Die [dritte Hypothese auf 4-Stunden-Kerzen](docs/slow-research.md) ist vorab
festgelegt. Der neue Downloader liest gezielt BTC/EUR aus dem vollständigen
Kraken-Archiv. Die Qualitätsprüfung fand zwei 4h-Lücken, die sich auch nicht
aus den Stundenkerzen schließen lassen. Der Versuch ist vor jeder
Ergebnisberechnung gesperrt und im Dashboard als solcher sichtbar. Die anschließende
[Prüfung der Einzeltrades](docs/data-reconciliation.md) hat die leeren Intervalle
bestätigt. Ein separat dokumentiertes Pausenmodell ermöglicht inzwischen die
Auswertung: 16 Läufe auf 2023/2024, Prüfung nicht bestanden, 2025 bleibt zurückgehalten.
Der [aktuelle Gebührenvergleich](docs/broker-costs.md) unterscheidet veröffentlichte
Brokerpreise von den älteren Modellannahmen.

1. **Weitere Forschung:** eine neue, strukturell begründete Hypothese ausschließlich
   auf den jetzt gesehenen Jahren 2023–2025 entwickeln und vor jedem Blick auf
   2026 unveränderlich festlegen.
2. **Ausführungsdaten verbessern:** den neuen öffentlichen
   [Perpetual-Beobachter](docs/perpetual-observer.md) über verschiedene
   Tageszeiten und Marktphasen laufen lassen, konservative Kostenperzentile
   festlegen, vollständige historische Funding-Sätze suchen und erst danach
   einen PAPER-Perpetual-Feed ergänzen.
3. **Brokerkonto prüfen:** EWR-Berechtigung, konkreten Marginplan, Collateral,
   minimale Ordergröße und API-Rechte lesend verifizieren; echte Orders bleiben gesperrt.

Der langfristige Weg bleibt: historische Daten → Backtesting → Paper Trading →
gesondert geprüfte Kraken-Demo/Testumgebung → erst wesentlich später optional LIVE.
Die spätere Demo-Anbindung muss über eine ausdrücklich getrennte Umgebung laufen;
die aktuelle Version enthält dafür noch keinen Client.

## Nachtarbeit: eigene Brokerdaten und Wiederaufnahme

- [Bitvavo-Datenanschluss](docs/bitvavo-data.md): rein öffentlich, eigene vollständige
  BTC/EUR-4h-Kurse 2023/2024 und aktuelle Instrumentregeln mit Originalbelegen.
- [Dauerhaftes Papierkonto](docs/paper-recovery.md): Zustand und Risikosperren
  nach Neustart prüfen und wieder aufnehmen; kein automatischer Strategie-Runner.
- Mindestmenge in BTC und Mindestbetrag in EUR werden unabhängig geprüft.
- Zwei langsamere Strategiehypothesen wurden vorab festgelegt und auf den bereits
  gesehenen Entwicklungsjahren getestet. Keine bestand die Auswahl; 2025 bleibt reserviert.
- [Arbeitsprotokoll](docs/overnight-progress.md) enthält Zwischenstand und offene Arbeit.

Der [Nachtbericht vom 23.09.2026](docs/night-report-2026-09-23.md) fasst die Forschung,
Brokerkosten, Betriebsprüfungen und nächsten Schritte zusammen.
