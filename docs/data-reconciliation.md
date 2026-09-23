# Prüfung der beiden leeren 4h-Intervalle

Die Intervalle 14.04.2024, 04:00–08:00 UTC, und 01.11.2025, 16:00–20:00 UTC,
sind auch in Krakens veröffentlichter Einzeltrade-Historie leer. Das ist kein
Beleg für einen bestimmten technischen Ausfallgrund oder für die Verfügbarkeit
von Orderbuch/Orders während dieser Zeit.

Öffentliche Originaldaten wurden mit dem historischen `since`-Cursor abgerufen.
Kraken dokumentiert diesen Zugang über seinen
[historischen Trade-Abruf](https://support.kraken.com/hc/articles/360029077772-python-code-to-retrieve-historical-time-and-sales-trading-history-)
und den [Trades-Endpunkt](https://docs.kraken.com/api-reference/market-data/get-recent-trades).

## Nachweise

| Datum | Eindeutige Trades im 12h-Prüffenster | Trades im fehlenden 4h-Intervall | ID davor → danach | Kontrollkerzen |
| --- | ---: | ---: | --- | --- |
| 14.04.2024 | 7.009 | 0 | 86171933 → 86171934 | beide bestanden |
| 01.11.2025 | 4.751 | 0 | 99976585 → 99976586 | beide bestanden |

Rohantworten inklusive fortlaufender Abfrage-Cursor und SHA256-Prüfsummen liegen
unter `data/evidence/kraken_trades_20240414` und `kraken_trades_20251101`.
Es wurden acht bzw. fünf Seiten geladen. Gleiche Trades an Seitengrenzen werden
per ID nur einmal gezählt; abweichende Duplikate führen zum Fehler. Eine Antwort
mit einem Trade jenseits der Endgrenze belegt den vollständigen Seitenlauf bis
über das Prüfintervall hinaus. Alle IDs innerhalb der Prüfintervalle sind fortlaufend.

Die jeweils vorhandene Kerze vor und nach der Lücke wurde aus Trades aufgebaut.
Open, High, Low, Close und Trade-Anzahl stimmen exakt mit dem Archiv überein.
Beim Volumen ist nur eine Abweichung unter einem halben Satoshi zulässig, um
Summationsreste des Archivs abzudecken; die beobachteten Unterschiede sind viel
kleiner. Berichtdateien: `data/evidence/reconciliation_20240414.json` und
`data/evidence/reconciliation_20251101.json`.

## Konsequenz für die Simulation

Der alte Versuch bleibt als wegen unvollständiger Kerzenabdeckung gesperrter
Protokollstand erhalten. Es wurden keine Flat-Kerzen ergänzt. Stattdessen wurde
vor jeder Performance-Berechnung `slow_4h_observed_v3` separat eingefroren:

- Nur die beiden durch Rohbelege bestätigten Intervalle sind zugelassen.
- In der Pause gibt es keine simulierten Einstiege, Ausstiege oder Bewertungen.
- Ein wartendes Einstiegssignal verfällt, statt Stunden später noch ausgeführt zu werden.
- Offene Positionen und alle Kontogrenzen bleiben bestehen; kein Neustart des Kontos.
- Ein Stop kann erst am nächsten beobachteten Kurs ausgeführt werden, einschließlich
  ungünstigem Kurssprung. Der Zeitpunkt ist der erste veröffentlichte Folge-Trade,
  auf Mikrosekunden aufgerundet, niemals davor.
- Indikatoren beginnen nach der Lücke erneut mit ihrer Aufwärmphase.
- Andere, ungeprüfte Lücken bleiben abgelehnt. Gewöhnliche Kerzen behalten das
  konservative OHLC-Modell; die Datenprüfung macht den gesamten Backtest nicht tickgenau.

Zusätzlich wurden aktuelle Kraken-Einstiegskosten und deren Verdoppelung in das
unveränderte Strategietest-Schema aufgenommen. Die Mindestanforderungen gelten
für **alle** Kostenfälle. Die Ergebnisse sind rückblickende Forschung; 2025 wird
nur bei erfüllter vorheriger Prüfung auf Strategie-Performance ausgewertet.
