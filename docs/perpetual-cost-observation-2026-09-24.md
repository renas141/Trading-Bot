# Kraken-Perpetual-Kostenbeobachtung, 23.–24.09.2026

## Ergebnis

Der erste zusammenhängende öffentliche Lauf für `PF_XBTUSD` ist abgeschlossen.
Zwischen 18:47:02 und 02:46:19 UTC wurden 480 Versuche ausgeführt. 477 waren
erfolgreich, drei schlugen vorübergehend fehl. Die Fehlerquote von 0,625 % liegt
unter dem vorab festgelegten Höchstwert von 5 %. Rohantworten und Prüfsummen aller
erfolgreichen Versuche wurden erneut geprüft.

| Qualitätsmerkmal | Ergebnis | Gate |
| --- | ---: | ---: |
| Erfolgreiche Minuten | 477 | mindestens 360 |
| Beobachtungsdauer | 7 h 59 min | mindestens 6 h |
| Fehlerquote | 0,625 % | höchstens 5 % |
| Größte Lücke zwischen Erfolgen | 120,37 s | höchstens 180 s |
| Höchstes Alter eines Analytics-Intervalls | 20,11 s | höchstens 180 s |
| Längster öffentlicher Abruf | 1,13 s | höchstens 20 s |

Das technische Kalibrierungstor ist bestanden. Dies ist ein Kostenkandidat für
neue Replays und kein Beleg für Strategieprofitabilität oder garantierte Fills.

## Beobachtete Kosten

Alle Werte außer Funding sind Basispunkte. Slippage wird zusätzlich zum jeweils
besten Geld-/Briefkurs gemessen.

| Größe | Median | 95. Perzentil | Maximum |
| --- | ---: | ---: | ---: |
| Gesamtspread | 0,119 | 0,119 | 0,475 |
| Kaufslippage 1.000 USD | 0,000 | 0,232 | 1,208 |
| Verkaufsslippage 1.000 USD | 0,000 | 0,117 | 1,095 |
| Kaufslippage 10.000 USD | 0,146 | 0,683 | 1,710 |
| Verkaufsslippage 10.000 USD | 0,139 | 0,736 | 1,986 |
| Kaufslippage 100.000 USD | 1,028 | 1,571 | 2,088 |
| Verkaufsslippage 100.000 USD | 1,085 | 1,603 | 2,666 |
| Kaufslippage 1 Mio. USD | 2,134 | 2,730 | 3,274 |
| Verkaufsslippage 1 Mio. USD | 2,213 | 2,956 | 3,532 |

Für das derzeitige 1.000-USD-Konto mit maximal 10x ist 10.000 USD die relevante
Obergrenze. Der konservative Kandidat verwendet deshalb den Gesamtspread-p95 von
`0.1193452718386929305828226350` und die höhere 10.000-USD-Slippage-p95 von
`0.7364486690794929510721478498`.

Bei separat belegten 0,05 % Takergebühr je Ausführung ergibt ein konservativ aus
den getrennten Randwerten zusammengesetzter Market-Roundtrip ungefähr 11,54
Basispunkte: zwei Gebühren, ein ganzer Spread sowie Kauf- und Verkaufsslippage.
Diese Addition kombiniert einzelne 95.-Perzentile und ist keine gemeinsam
beobachtete Roundtrip-Verteilung.

Der relative Funding-Wert lag zwischen `-0.000001778091666667` und
`0.000004444079166667` pro veröffentlichtem Stundenwert. Der Kostenkandidat setzt
für eine Vierstunden-Kerze vorsichtig viermal den betragsmäßig ungünstigsten Wert
an: `0.000017776316666668`, entsprechend rund 0,178 Basispunkten.

## Belege und Verwendung

- SQLite-Beleg: SHA-256 `57d84d30da0c8e21c72556762c6767cd9b52b23e74eb7cf59404fbeda4bad83e`
- Zusammenfassung: SHA-256 `96996e7246fce45227bd8412bd5176156822a8359bcf8ddd5db3ef6dfff61400`
- Kostenkandidat: SHA-256 `32599bc1c6d137b89863b14cd62f1ce2cb2960f2200a06545cbb3ad7dd0656d7`

Die Belege liegen lokal unter
`data/evidence/perpetual-costs-20260923-evening/` und werden wegen ihrer Rohdaten
nicht in Git eingecheckt. Der geprüfte Lader berechnet das Gate erneut, bindet den
Kandidaten an die Zusammenfassung und verlangt eine separate Gebührenquelle.

## Grenzen und nächster Einsatz

Acht Stunden decken nur einen Ausschnitt einer Marktphase ab. Kraken veröffentlicht
geschätzte Durchschnittspreise, keine zugesicherten Fills. Historische Funding-
Vollständigkeit, private Kontobedingungen, Ausfälle unter Last sowie verschiedene
Wochenend- und Volatilitätsphasen bleiben offen.

Die Werte dürfen ausschließlich in einer neuen, vorab registrierten Replay-Studie
verwendet werden. Die alten Ergebnisse bleiben unverändert. Eine spätere
PAPER-Freigabe verlangt zusätzliche Läufe in anderen Marktphasen und einen
simulierten Perpetual-Feed; LIVE bleibt gesperrt.
