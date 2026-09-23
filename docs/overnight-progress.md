# Nachtarbeit 22./23. September 2026

## Auftrag und Grenzen

Der Nutzer hat selbstständige chronologische Weiterentwicklung bis zum Morgen
autorisiert: Daten, seriöse Strategieforschung, reale Brokergebühren und die
Voraussetzungen für anwendbares Paper Trading. Abschlussbericht ausdrücklich mit
gpt-5.6-luna, anschließend selbst prüfen. Keine echten Orders, kostenpflichtigen
Dienste oder Konteneröffnungen. LIVE bleibt gesperrt. Keine Gewinnversprechen.

Heartbeat `trading-bot-ber-nacht-weiterentwickeln` ist stündlich aktiv; spätestens
23.09.2026 um 08:00 Europe/Berlin Abschluss erstellen und Automation pausieren.
Nicht blind das Limit verbrauchen: sinnvolle überprüfbare Fortschritte priorisieren.

## Ausgangsstand

- Modulare Python-Software, vollständig finanzierte LONG-Simulation, SQLite,
  Kosten-/Risikomodell, historische Next-Open-Tests und lokales Dashboard.
- Zwei 15m-Hypothesen auf Q1/Q2 2026 negativ. Diese Zeiträume gelten als gesehen.
- Dritte Hypothese: unveränderte Ausbruchsregel plus Nettoziel-Filter auf 4h.
  2023/2024 prüfen, 2025 nur bei bestandenem Gate. Noch keine Performance auf
  2023–2025 berechnet. Originalprotokoll: `data/research/slow_4h_2023_2025_v2`.
- 150 Tests bestanden vor den hier folgenden Änderungen.
- Dashboard läuft auf 127.0.0.1:8765, Prozesssession 16831. Neustart nach Installation
  geänderter Dashboard-Dateien nötig. Keine privaten APIs vorhanden.

## Aktueller Befund: Original-Trades geprüft

Neue Module `app/market_data/trade_history.py` und `reconciliation.py` sind implementiert
und getestet. Auch das separate Pausenmodell ist implementiert und getestet.
Gesamtsuite: **163 Tests bestanden** (23.09.2026, ca. 00:17 Berlin).

- Öffentliche Kraken-Trades abgefragt: acht Seiten für 14.04.2024, fünf Seiten für
  01.11.2025, jeweils 12h inklusive Kontrollkerze davor und danach.
- Rohbelege unter `data/evidence/kraken_trades_20240414` und `kraken_trades_20251101`.
- 7.009 bzw. 4.751 eindeutige Trades im Zeitfenster; gleiche Überlappungen an
  Seitengrenzen per ID dedupliziert. Endgrenzen durch nachfolgende Trades belegt.
- In beiden fehlenden 4h-Intervallen sind **keine veröffentlichten Trades** vorhanden.
  IDs vor/nach den Pausen sind fortlaufend:
  86171933 → 86171934 (14.04.2024 03:00:15.028644 bis 09:52:54.423614 UTC),
  99976585 → 99976586 (01.11.2025 15:02:37.172512 bis 21:46:15.161570 UTC).
- Alle vier Kontrollkerzen stimmen in OHLC und Anzahl exakt überein. Volumen wird
  innerhalb < 0,5 Satoshi verglichen, weil das Archiv Summationsreste im Sub-Satoshi-
  Bereich enthält. Kein gelockerter Kurs-/Anzahlvergleich.
- Berichte: `data/evidence/reconciliation_20240414.json`, `reconciliation_20251101.json`.
  Beide klassifizieren `empty_in_public_trade_history`, Kontrollen bestanden.
- Das belegt den Zustand der veröffentlichten Kraken-Historie, nicht unabhängig
  den technischen Grund oder die Verfügbarkeit der Börse. Keine erfundenen OHLC.

## Nächste Schritte, in Reihenfolge

Aktualisierung 00:20: Schritte 1 (außer Dashboard-Neustart), 2, 3 und wesentliche
Gebührenrecherche aus 4 sind fertig. `data/research/slow_4h_observed_v3` wurde vor
Performance eingefroren und hat 16 Läufe auf 2023/2024 abgeschlossen. Screen negativ:
Nettofilter 2023 altes Basismodell +74,64 EUR/32 Trades, 2024 -41,06 EUR/23 Trades;
aktuelle Krakenkosten 2023 +34,34 EUR/5 Trades, 2024 -6,99 EUR/5 Trades;
Kraken-Stress beide 0 Trades. **2025 nicht auswerten, Gate nicht bestanden.**

Gebührenquellen frisch geöffnet: Kraken Tier 1 Spot 0,40 % Maker / 0,80 % Taker
(Umstellung Juli 2026), Coinbase Advanced EU/UK seit 16.09.2026 0,25/0,50 %, Bitvavo
EUR 0,15/0,25 %. Siehe docs/broker-costs.md. Keine rabattierten Maker-Fills annehmen.

Nächstes konkret: Dashboard-Kostenfälle und Datenprüfungsnachtrag testen/restarten,
dann maximal zwei vorab dokumentierte langsamere Strategiehypothesen auf den jetzt
gesehenen 2023/2024 als **Entwicklung** prüfen (keinen neuen OOS-Nachweis behaupten).
2025 bleibt global zurückgehalten bis ein separat festgelegtes Auswahlverfahren
abgeschlossen ist. Parallel im sachlichen Ablauf öffentlicher Bitvavo-Datenadapter
und robuste Paper-Wiederaufnahme; keine anderen Agenten ohne ausdrücklichen Auftrag,
außer dem ausdrücklich gewünschten Luna-Abschlussbericht.

1. Collector und Abgleich testen, Datenprüfungsbericht/Dashboard aktualisieren.
2. Separates Modell für explizit geprüfte leere Intervalle: keine Ein-/Ausstiege
   im leeren Intervall; ausstehende Einstiege verfallen; offene Positionen bleiben
   bestehen und werden am nächsten beobachteten Kurs konservativ behandelt.
   Indikator-Historie nach der Lücke neu aufwärmen. Ungeprüfte Lücken weiter ablehnen.
   Kein rückwirkender Exit vor der Pause, kein Konto-Reset, keine künstliche Equity.
3. Vor Performance-Berechnung neues Protokoll mit begründeter Quellen-/Modelländerung
   einfrieren. Bisherige Protokolle unverändert archivieren. Jahres-/Kosten-Gates
   nicht nach Ergebnissen lockern; primärer Kandidat bleibt festgelegt.
4. Offizielle Brokergebühren recherchieren, besonders Kraken Pro BTC/EUR und
   geeignete EUR-Alternativen. Maker-Kosten ohne realistisches Fill-Modell nicht
   als garantierte Einsparung rechnen. Andere Börsengebühren auf Kraken-Kursen
   nur als Kostensensitivität, nicht als Broker-Backtest ausgeben.
5. Neue vorab festgelegte Hypothesen und robuste Paper-Betriebsvoraussetzungen
   nach Erkenntnissen priorisieren. Bis zum Morgen am tatsächlichen Stand berichten.

## Hinweise für Fortsetzung

Bestehende strikte Forschung bindet den gesamten Quellbaum; neue Module lassen
alte Code-Gleichheit erwartungsgemäß scheitern. Alte Protokolle nicht überschreiben.
Snapshot des damaligen Codes liegt unter `slow_4h_2023_2025_v2/source`.
Standardtest: `.venv/bin/python -m unittest discover -s tests -q`.
Paket neu installieren mit lokalem uv, --frozen --no-editable --offline und
--reinstall-package modular-crypto-trading-bot; Cache unter /private/tmp.
Kein Git-Commit/Push erfolgt; ursprüngliche Projekterstellung noch untracked.

## Fortschritt 23.09.2026, 05:12 Berlin

- Zweite neue Studie `slow_candidates_development_v1` abgeschlossen: 16 Läufe,
  langsamer Ausbruch + Trend-Rücksetzer. Kein Kandidat qualifiziert; 2025 ungesehen.
  Langsamer Ausbruch: Kraken aktuell 2023 +12,05 / 2024 -25,42 EUR;
  Stress -19,67 / -20,74 EUR. Rücksetzer in allen Entwicklungsfällen negativ.
- Öffentlicher Bitvavo-Adapter + Collector implementiert, 8 Tests bestanden.
  API end ist eine ausgerichtete Schlussgrenze; ein echter Zweikerzen-Probeabruf
  bestätigte: nicht 1 ms abziehen, sonst geht die letzte Kerze verloren.
- `data/datasets/bitvavo_btc_eur_4h_2023_2024`: alle 4.386 Kerzen vorhanden,
  keine Lücken, vier Seiten mit Originalantworten/Hashes gespeichert.
- `data/evidence/bitvavo_snapshot_20260923`: aktueller Tick 1 EUR, Mengenminimum,
  Notionalminimum und ein Geld-/Brief-Snapshot. Kein historischer Spreadbeleg.
- `DurablePaperBroker` implementiert: explizite PAPER-Wiederaufnahme, atomare
  Ledger-/Checkpoint-Transaktionen, Risikolatches/Peak/UTC-Tag bleiben erhalten,
  Rechnungsabgleich, Versionssperre gegen alten zweiten Schreiber. 10 Tests bestanden,
  darunter Speicherfehler-Rollback, geschlossene Verbindung, verfälschte/fehlende
  Belege und geänderte Gebühren. Noch kein autonomer Paper-Daten-/Strategie-Runner.
- Repository jetzt Schema 3; alte 1/2 migrieren, Dashboard liest 2/3. Diagnostics-
  Leser wurde ebenfalls angepasst. Mindestmenge im Basiswert ergänzt, unabhängig
  vom EUR-Mindestbetrag, beides im Risikomanager und Broker geprüft.
- Vollsuite nach Änderungen hatte fünf Fehler: drei durch den zuvor vergessenen
  Diagnostics-Schema-Check, zwei durch uhrzeitabhängige Test-Auswahl `catalog[0]`.
  Ursachen korrigiert, erneute gezielte Prüfung läuft. Nicht als bestanden melden,
  bevor vollständiger erneuter Lauf grün ist.
- Bitvavo-Vergleichsmodul `backtesting/venue_research.py` fertig: exakt bestehende
  drei Varianten, eigenes 2023/24, .25/.50 % Taker, aktuelle Instrumentgrenzen,
  nur Entwicklung ohne Holdout-Auswahl. v1 nach Freeze vor Performance abgebrochen,
  weil oben erwähnte Diagnostics-Kompatibilität noch korrigiert werden musste.
  `aborted.json` erklärt das; v2 als nächstes einfrieren/auswerten.
- Dashboard-Prozess aktuell Session 1761, installierter Stand veraltet. Nach allen
  Änderungen neu installieren, neu starten und im Browser prüfen.

Nächste sinnvolle Arbeit: Bitvavo-Vergleich ausführen, neuen Eintrag im Dashboard
sichtbar machen, Vollsuite abschließen, Papier-Wiederaufnahme dokumentieren und
falls Zeit einen bounded öffentlichen Quote-Sampler für echte Spreadbeobachtungen.
Bis 08:00 Berlin Ende; Luna erst für den abschließenden Bericht verwenden.

## Fortschritt 05:16 Berlin

- Bitvavo-Vergleich v2 vollständig (12 Läufe). Langsamer Ausbruch normal:
  2023 +43,29 EUR (6 Trades), 2024 +15,22 EUR (12); Stress +30,17 / -1,66 EUR.
  Kein Kandidat positiv in allen vier Fällen. Nettoziel-Filter normal +88,12 /
  -25,37 EUR, Rücksetzer normal -31,39 / -24,18 EUR. Keine Holdout-/Handelsfreigabe.
- Vollsuite 187 Tests grün; danach 2 Quote-Monitor-Tests ergänzt, gezielt grün.
- Quote-Monitor läuft in Session **34069**, `data/evidence/bitvavo_quotes_overnight_20260923`,
  maximal 160 Versuche im Minutenabstand, Schluss spätestens 05:45 UTC / 07:45 Berlin.
  Daten und Kurzbericht werden nach jedem Versuch gespeichert. Keine Orders.
- Dashboard Session **78519**; Katalog mit 6 Studien / 56 abgeschlossenen Läufen
  gegen jeweilige Datenbank geprüft. Browser hat Bitvavo-Vergleich erfolgreich geladen.
  Letzter kleiner UI-Fix (Jahresauswahl Ende inkl. 31.12., Einordnungstitel für Broker-
  Vergleich, leere Kostenwahl bei gesperrter Studie) ist noch nicht neu installiert.
- docs/paper-recovery.md und docs/bitvavo-data.md erklären genaue Fähigkeiten und Grenzen.
- Nächster Schwerpunkt vor Abschluss: eigenständiger PAPER-Beobachtungsrunner mit
  aktualitätsgeprüften öffentlichen Quotes, idempotenten Ereignissen und gemeinsamem
  Fortschritts-/Portfolio-Checkpoint. Standard weiterhin no_trade; keine ungeprüfte
  Forschungsstrategie für automatischen Handel aktivieren. Nicht länger als 08:00.

## Fortschritt 05:25 Berlin

- QuotePaperRunner + app.paper_cli implementiert. Idempotente Ereignisse,
  atomarer Runner-/Portfolio-Fortschritt, nur neue abgeschlossene Kerzensignale,
  Bid/Ask-Ausführung mit separater Slippage, Alters-/Tiefe-/Instrumentprüfungen.
  Schutzexit auch bei fehlenden Kerzen; historische Startsignale nur Warm-up.
- 9 Runner-Tests und 2 Settings-/CLI-Tests grün. Vollsuite jetzt **200 Tests grün**.
- Öffentlicher PAPER-Start einmal erfolgreich, anschließend dieselbe Session mit
  --resume fortgesetzt. Ordner `data/paper/bitvavo_observer_20260923`; Prozesssession
  siehe letzte Toolausgabe (nachtragen). Max. 160 Beobachtungen, Ende 07:45 Berlin.
  Default ausschließlich no_trade, keine Forschungsstrategie automatisch aktiviert.
- Der separate Quote-Monitor läuft weiter (Session34069). Es handelt sich um eine
  begrenzte Beobachtungsstichprobe, keinen Beleg typischer/historischer Spreads.
- Dokumentation der neuen Runner-Grenzen steht in docs/paper-recovery.md.

## Fortschritt 05:32 Berlin

- PAPER-Beobachter läuft in Session **50791** (dieselbe virtuelle Session wie beim
  ersten Einzelstart), Quote-Monitor separat in 34069; beide bis 07:45 Berlin.
- Weitere vorher eingefrorene Hypothese `bitvavo_trailing_development_v1` abgeschlossen:
  12 Läufe mit gefiltertem Fixziel-Kontrollfall, ungefiltertem Fixziel und nachgezogenem
  Stop. Identische langsame Ausbruchseinstiege, initial 3*ATR42, Trailing = höchster
  Schluss seit Einstieg minus 3*ATR42, niemals gelockert, erst ab Folgekerze wirksam.
- Trailing normal: 2023 +50,34 EUR / 8 Trades; 2024 +11,69 EUR / 12 Trades.
  Stress: +30,77 / -4,73 EUR. Gate nicht bestanden (2024 Stress negativ, zudem
  schlechter als Fixzielkontrolle 2024). Keine nachträgliche Regeländerung.
- Neuer trailing Backtest speichert alle Stop-Anpassungen in exit_updates. Initialer
  Positionsstop bleibt nachvollziehbar. Nicht in den laufenden PAPER-Modus integriert.
- Neue 3 Trailing-Tests plus bestehende Ausführungstests gezielt grün. Vollsuite
  nach diesen Änderungen noch ausführen; zuletzt vollständig grün waren 200 Tests.
- Dashboard-Code für siebte Studie/Stopdetails ergänzt; noch neu installieren/starten.
- Es liegen nun 68 abgeschlossene Forschungsläufe vor (einschließlich älterer).
  2025 bleibt hinsichtlich Strategieperformance ungesehen.

## Qualitätssicherung 05:36 Berlin

- Gesamtsuite nach allen Engine-/Runner-Änderungen: **203 Tests grün**.
- 106 Python-Quellen ohne Bytecode-Schreibzugriff syntaktisch geprüft, JavaScript
  geprüft. Erster Versuch mit System-Python scheiterte lediglich am nicht freigegebenen
  macOS-Cachepfad; anschließende Prüfung im Projektinterpreter erfolgreich.
- Alle 7 Studien / 68 abgeschlossenen Läufe mit gespeicherten DB-Ergebnissen verglichen;
  SQLite integrity_check und foreign_key_check fehlerfrei. Keine Holdout-Ordner für 2025.
- Luna-Agent /root/luna_report hat docs/night-report-2026-09-23.md als Entwurf erstellt
  (ca.641 Wörter). Bestätigung zu 203 Tests wurde ihm mitgeteilt. Endmesswerte nach
  07:45 fehlen noch; bitte ihn per followup_task um Finalisierung bitten und selbst prüfen.
- Inhaltliche Korrekturen für finalen Bericht: Gebührenvergleiche klar trennen: eigene
  Bitvavo-Kurse vs bloße Fremdgebühren-Sensitivität auf Kraken. Vorhandene Gates existieren,
  sind aber nicht bestanden; nicht behaupten, es fehle jegliches Auswahlverfahren.
  Neue positive Hypothese müsste vorher definiert und qualifiziert werden.
  Höhere Gebühren können beim Nettofilter eine andere Trade-Auswahl bewirken; Stress-
  Ergebnis dadurch gelegentlich besser, kein wirtschaftlicher Vorteil höherer Kosten.
- Dashboard neu installiert und neu gestartet (Session aus letzter Toolausgabe).
  Abschließende Browserprüfung noch durchführen.

## Abschluss 23.09.2026, 15:20 Berlin

Die Nachtentwicklung ist abgeschlossen; danach wurden nur Enddaten und Bericht geprüft.
Luna hat docs/night-report-2026-09-23.md finalisiert; der Hauptagent hat Zahlen und
Aussagen geprüft und präzisiert (sechs ausgewertete Studien plus gesperrter Originalplan).

- 151/151 Quote-Beobachtungen erfolgreich, 0 Fehler, 05:14:14–07:44:31 Berlin.
  Median 0,131621 bps, Maximum 0,394698 bps; geringste sichtbare Ask-Menge 7,67 EUR.
  Kurzes Zeitfenster, keine Börsen-Ereigniszeitstempel, keine garantierte Markttiefe.
- PAPER: 140 Ereignisse/Kontobewertungen, 1 HOLD um 06:00 Berlin, 0 Orders,
  Positionen und Trades, 0 Pollfehler, 1.000 EUR, um 07:45 Uhr pausiert.
- Quote-Zusammenfassung aus Rohdaten erneut berechnet und identisch; SQLite-Integrität
  und Fremdschlüssel geprüft. Paper-Wiederaufnahme auf unabhängiger Datenbankkopie
  erfolgreich; Originaldatei vor/nach identisch gehasht. Keine neue echte oder Paper-Order.
- 203 Tests waren nach den letzten Codeänderungen vollständig grün. Kein erneuter
  unveränderter Testlauf für den Bericht. Dashboard-Browserprüfung inkl. Trailing-
  Trade-Details ist abgeschlossen, laufender Server Session39738.
- Automatische Freigabeprüfung verweigerte zuvor die Terminänderung auf07:50 wegen
  Nutzungslimit. Deshalb verspäteter Abschluss. Am Nachmittag existiert die Automation
  laut automation_update nicht mehr (möglicherweise manuell entfernt); Update auf
  PAUSED meldete ausdrücklich „does not exist“. Sie wurde nicht neu angelegt.
- Alle Ergebnisse lokal; keine Commits oder Pushs vorgenommen. 2025 bleibt bezüglich
  Strategieperformance ungesehen. Keine belastbar profitable Strategie und keine
  automatische Handelsfreigabe.
