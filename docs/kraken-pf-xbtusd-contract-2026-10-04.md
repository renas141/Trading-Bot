# Aktuelle PF_XBTUSD-Vertragsprüfung, 04.10.2026

Am 04.10.2026 um 00:06 UTC wurden Krakens öffentliche Instrument- und
Statusendpunkte erneut gelesen. Der vollständige Rohbestand liegt lokal unter
`data/evidence/kraken_derivatives_20261004` und ist durch SHA-256-Prüfsummen
gebunden. Der Abruf nutzte keine Zugangsdaten und keine Orderfunktion.

| Merkmal | Kraken | Lokales Modell | Ergebnis |
| --- | ---: | ---: | --- |
| Preisschritt | 1 USD | 1 USD | gleich |
| Mengenschritt aus Präzision | 0,0001 BTC | 0,0001 BTC | gleich |
| EWR-Retail Anfangsmargin, erste Stufe | 10 % | 10 % | gleich |
| EWR-Retail Erhaltungsmargin, erste Stufe | 5 % | 5 % | gleich |
| Daraus abgeleiteter maximaler Hebel | 10x | harter Deckel 10x | gleich |
| Handelbar / abgelaufen | ja / nein | Voraussetzung | erfüllt |
| Preisverschiebung / Extremvolatilität | nein / nein | Einstiegssperre | erfüllt |

Kraken wies außerdem eine Kontraktgröße von 1 und eine veröffentlichte maximale
Positionsgröße von 1.200 aus. Diese öffentliche Obergrenze ist keine persönliche
Kontofreigabe. Die öffentliche Antwort enthielt keine `minimumTradeSize`; eine
Mindestgröße darf deshalb nicht daraus erfunden werden.

Der neue Prüfer bindet den vollständigen Instrumentkatalog, den aktuellen
Marktstatus und die berechnete Zusammenfassung getrennt per Prüfsumme. Er scheitert
geschlossen, wenn `PF_XBTUSD` fehlt, mehrfach vorkommt, nicht handelbar oder
abgelaufen ist, die EWR-Privatkundenstaffel fehlt, der Markt eine Preisverschiebung
oder Extremvolatilität meldet oder lokale Tick-, Mengen- und Marginannahmen nicht
mehr konservativ sind.

Die offizielle Schnittstellenbeschreibung steht unter
[Get instruments](https://docs.kraken.com/api-reference/instrument-details/get-instruments)
und [Instrument status](https://docs.kraken.com/api-reference/instrument-details/get-instrument-status-list).
Kraken weist außerdem darauf hin, dass Marginstaffeln ohne Vorankündigung geändert
werden können. Deshalb ist dies ein zeitgebundener Beleg, keine dauerhafte
Handelsfreigabe.

Die konkrete Mindestgröße und Produktfreigabe liefert erst Krakens angemeldeter
[Get trading instruments](https://docs.kraken.com/api-reference/instrument-details/get-trading-instruments)-Endpunkt.
Dieser reine Lesezugriff ist im Kontoprüfer vorbereitet, kann aber erst mit einem
persönlichen `READ_ONLY`-Schlüssel ausgeführt werden.

