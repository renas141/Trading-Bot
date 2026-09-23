# Risk Engine und Backtest-Ausführung

Diese Ausbaustufe simuliert vollständig finanzierte BTC/EUR-LONG-Positionen bei
1x. LIVE ist unverändert gesperrt. Die ausgelieferte `NoTradeStrategy` erzeugt
keine Handelsentscheidungen; die Handelsmechanik wird mit expliziten Testsignalen
geprüft. Das ist keine Strategie- oder Profitabilitätsaussage.

## Ablauf einer Kerze

1. Das Portfolio wird zum Kerzenbeginn bewertet. Bereits offene Positionen mit
   überlaufenen Stops/Zielen werden geschlossen.
2. Das Signal vom Schluss der vorherigen Kerze wird am neuen Eröffnungspreis
   geprüft. Erst jetzt wird die Positionsgröße berechnet und ggf. ausgeführt.
3. Stops und Ziele werden anhand von High/Low geprüft, auch für neu eröffnete
   Positionen. Wenn beide erreicht werden, gewinnt konservativ der Stop.
4. Das Portfolio wird zum Schluss bewertet. Die Strategie erhält nur die bisher
   abgeschlossenen Kerzen und erzeugt das Signal für die folgende Kerze.

Das letzte Signal wird mit einem dokumentierten Ablehnungsgrund gespeichert,
weil eine Folgekerze fehlt. Verbleibende Positionen werden am letzten Schlusskurs
mit Ausführungskosten und Grund `END_OF_DATA` geschlossen. So sind Endkapital
und abgeschlossene Trade-Ergebnisse abstimmbar.

## Positionsgröße und Limits

Ein LONG-Signal darf einen absoluten `stop_price` und optional einen
`take_profit_price` vorschlagen. Ein Stop unterhalb des aktuellen Einstiegspreises
ist zwingend. Das Ziel muss über dem simulierten Kaufpreis liegen. Springt der
Markt bis zur Ausführung über diese Grenzen, wird der Einstieg abgelehnt.
Confidence gewährt keine Ausnahme von den Limits.

Die Risk Engine berechnet den geschätzten Verlust je BTC als Kaufpreis inklusive
Einstiegsgebühr minus Netto-Verkaufserlös am Stop. Spread, Slippage und Rundung
sind in beiden Preisen berücksichtigt. Das kleinste verfügbare Budget aus
Einzeltrade-Risiko, Gesamtrisiko, Tagesverlust und Drawdown bestimmt die Menge.
Guthaben, maximale Positionsgröße und Positionszahl begrenzen sie zusätzlich.
Die Menge wird immer abgerundet; zu kleine Orders werden abgelehnt.

Bei bestehenden Positionen zählt der potenzielle Rückgang vom aktuellen
Netto-Verkaufswert bis zum Stop als offenes Risiko. Dadurch werden auch bereits
aufgelaufene Buchgewinne berücksichtigt, die bei unverändertem Stop wieder
verloren gehen könnten. Positionen ohne bewertbaren Schutzstop verhindern
zusätzliche Einstiege.

Beispiel ausschließlich zur Rechenprüfung: Bei 1.000 EUR Kapital, einem
Risikobudget von 1%, Einstieg 100 und Stop 90 ergibt sich ohne Kosten eine Menge
von 1. Mit Kosten sinkt die zulässige Menge. Die Tests prüfen außerdem, dass
Endguthaben, Netto-Trade-P&L und gezahlte Gebühren exakt zusammenpassen.

Der Broker wiederholt die zentrale Risikoprüfung unmittelbar vor dem Einstieg.
Eine vorgeschlagene Menge oberhalb der aktuell erlaubten Menge, ein abweichender
Stop oder eine unzulässige Rundung werden auch mit einer vorgelegten Freigabe
abgelehnt. Python-Schnittstellen sind weiterhin keine Sandbox für fremden Code.

## Tagesverlust, Drawdown und Kill Switch

- Equity = verfügbares Guthaben plus angenommener Netto-Verkaufserlös aller
  offenen Positionen. Damit sind unrealisiertes P&L und Exit-Kosten enthalten.
- Ein UTC-Tageswechsel verwendet die letzte Equity des Vortags als Basis.
  Ein Verlust durch die neue Eröffnungslücke zählt damit zum neuen Tag.
- Erreicht die beobachtete Equity die Tagesverlustgrenze, bleiben Einstiege bis
  zum nächsten UTC-Tag gesperrt, auch wenn sich die Equity zwischendurch erholt.
- Eine erreichte Drawdown-Grenze sperrt neue Einstiege für die gesamte Session.
- `KILL_SWITCH=true` sperrt beim Start. `broker.trip_kill_switch()` kann eine
  laufende Session für neue Einstiege sperren. Schließen bleibt immer möglich.

Die Grenzen werden an beobachteten Eröffnungs-, Ausführungs- und Schlussereignissen
geprüft, nicht an einem unbekannten Tickpfad. Sie verhindern neue Einstiege;
sie lösen selbst keine zusätzliche Zwangsliquidation aus. Schutzstops bleiben aktiv.
Kurslücken können Verluste oberhalb des geplanten Budgets verursachen. Ein Stop
ist in dieser Simulation kein garantierter Ausführungspreis.

## Ausführungskosten und Kerzenannahmen

`PAPER_SPREAD_BPS` ist der gesamte angenommene Spread. Je Seite wird die Hälfte
plus `PAPER_SLIPPAGE_BPS` ungünstig auf den Referenzpreis angewandt. Kaufen rundet
auf `PRICE_TICK` auf, Verkaufen ab. `QUANTITY_STEP` bestimmt die Mengenrundung,
`MIN_ORDER_NOTIONAL` den Mindestwert. Die Defaults sind Forschungsannahmen und
keine zugesicherten Kraken-Handelsbedingungen.

Bei einer Eröffnung unter dem Stop wird zum schlechteren Eröffnungspreis
abzüglich Ausführungskosten geschlossen (`STOP_GAP`). Liegt die Eröffnung über
dem Ziel, wird konservativ keine Verbesserung über das Ziel angenommen
(`TAKE_PROFIT_GAP`). Ziele sind hier vereinfachte Marktverkäufe nach Auslösung,
keine garantierten Limit-Fills. Berührt eine Kerze Stop und Ziel, lautet der
Exit-Grund `STOP_FIRST_AMBIGUOUS_BAR`.

Intrabar-Exits und Schlussbewertungen erhalten buchhalterisch den letzten
Mikrosekundenzeitpunkt innerhalb der Kerze (`closed_at - 1 µs`), weil der tatsächliche
Ausführungszeitpunkt unbekannt ist. Das ordnet insbesondere die letzte Kerze
vor Mitternacht dem richtigen UTC-Tag zu. Es behauptet keine Zeitgenauigkeit.
Bei mehreren Positionen beschreibt das
Journal eine deterministische Simulationsreihenfolge, keinen rekonstruierten
Tickverlauf. Equity-Kennzahlen beziehen sich auf diese beobachteten Ereignisse;
ein genauer Drawdown innerhalb einer Kerze ist damit nicht bestimmbar.

Nicht enthalten: SHORT-Ausführung, Hebel, Funding, Liquidation, Orderbuch,
Teilfüllungen, Latenz, dynamische Stops oder Teilverkäufe. `MIN_LIQUIDATION_DISTANCE`
bleibt für spätere Derivate reserviert; bei vollständig finanzierten Spot-Positionen
ist keine Liquidationsschwelle zu berechnen.

## Ergebnisse und Nachvollziehbarkeit

Der Backtest gibt eine JSON-Zusammenfassung aus und speichert sie mit Session-ID
in `backtest_results`. Hinterlegt werden die Kosten-/Risikoparameter, die
Ausführungsmodell-Version und eine Prüfsumme der Eingabedatei. SQLite-Schema 1
wird verlustfrei um diese Tabelle auf Version 2 erweitert.

Enthalten: Nettoergebnis, Rendite als Bruchteil, Trade-Anzahl, Gewinne/Verluste/
Nullergebnisse, Win Rate, Average Win/Loss, Profit Factor, Expectancy, beobachteter
Max Drawdown, Gebühren sowie LONG/SHORT-Aufteilung. Average Loss ist negativ.
Ohne Trades sind entsprechende Quoten `null`; ohne Verlusttrades ist der Profit
Factor ebenfalls `null`, da der Nenner null wäre. Sharpe wird nicht aus den
unregelmäßigen Ausführungsereignissen berechnet.

## Start und gezielte Tests

```bash
TRADING_MODE=BACKTEST LOG_LEVEL=WARNING python main.py \
  --dataset data/datasets/kraken_btc_eur_15m_initial

python -m unittest tests.test_risk tests.test_simulation -v
```

Der erste Befehl verwendet weiterhin `NoTradeStrategy`: erwartetes Ergebnis
1.000 EUR unverändertes Kapital, keine Orders und null Trades. Die Tests erzeugen
synthetische Signale nur in temporären Datenbanken und prüfen tatsächliche
simulierte Einstiege, Stop-/Ziel-Exits, Kurslücken, Kosten und Verlustsperren.

Als Nächstes kann eine separat entwickelte Strategie über die `Strategy`-Schnittstelle
an denselben Backtester angebunden werden. Die erste solche Hypothese ist bereits
als `trend_breakout` vorhanden und ausschließlich per expliziter BACKTEST-Auswahl
verfügbar. Die getrennte Quartalsauswertung steht in [research.md](research.md).
Breitere unabhängige Daten und zusätzliche Validierung bleiben erforderlich.
