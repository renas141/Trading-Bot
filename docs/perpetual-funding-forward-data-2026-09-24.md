# PF_XBTUSD-Funding für künftige Forward-Tests

Stand: 24.09.2026. Der öffentliche Kraken-Funding-Endpunkt ist für aktuelle
Stunden nutzbar, lieferte für einen Prüfzeitraum Anfang 2025 aber eine leere
Reihe. Die Studien 2023–2025 können deshalb nicht nachträglich mit einer
vollständigen echten Funding-Historie versehen werden.

Der neue Archivbaustein akzeptiert nur `PF_XBTUSD`, den festen Kraken-HTTPS-Host,
Stundenintervalle und vollständig abgeschlossene Bereiche bis höchstens sieben
Tage. Er folgt keinen Weiterleitungen, begrenzt Antwortgrößen und verwirft den
gesamten Zielordner bei fehlenden, doppelten oder unerwarteten Stunden. Rohantwort,
normalisierte Vorzeichenreihe und Qualitätsbericht sind über SHA-256 gebunden.
Die offizielle Feldbeschreibung steht im
[Kraken API Center](https://docs.kraken.com/api/docs/futures-api/charts/market-analytics).

## Erster vollständiger Tag

Der lokal gespeicherte Zeitraum reicht vom 23.09.2026 00:00 UTC bis zum
24.09.2026 00:00 UTC, Ende exklusiv:

- 24 von 24 Stunden vorhanden, keine Lücke;
- 21 positive und 3 negative `relativeRate`-Schlusswerte;
- Summe für einen durchgehend gehaltenen Long: `0.000169321362499998`, also
  rund 0,01693 % des Nominals;
- Vierstunden-Summen: `0.000024723445833333`, `0.000039165020833332`,
  `0.000044266750000000`, `0.000053298441666666`,
  `0.000002850033333334`, `0.000005017670833333`.

Das Vierstundenmittel von rund `0.00002822` lag an diesem Tag über der bisherigen
primären nachteiligen Sensitivität `0.00001778`, aber unter deren doppeltem
Stresswert. Ein einzelner Tag reicht nicht aus, um die Kostenannahme neu zu
kalibrieren. Für künftige Forward-Replays kann die echte signierte Reihe dagegen
direkt verwendet werden: positive Sätze belasten Long-Positionen und entlasten
Short-Positionen, negative Sätze umgekehrt.

| Datei | SHA-256 |
| --- | --- |
| Manifest | `cba252ddf0359e95e89ee00aa4f8da288bcbd9b73177faf8313ffeeade2e4c37` |
| Rohantwort | `0882971a24637e59582dfb2e09f195ac9c221825605a939904d341c85dbbbbdd` |
| Funding-CSV | `d4a999c49da3f609af7dc5cdcc7989bc2736654cc66f0809c2db091dd15499d1` |
| Qualitätsbericht | `5a067a29d85f2164a21f5f284c07ae0b906db890bfaa92e704b0c700fc170245` |

Der Datensatz liegt im von Git ausgeschlossenen lokalen Datenbereich. Er
aktiviert keine Strategie und sendet keine Orders.
