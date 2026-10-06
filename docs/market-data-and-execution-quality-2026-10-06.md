# Marktdaten und Ausführungsqualität, 06.10.2026

## Neue Datenbasis

Der neue öffentliche PF_XBTUSD-Historienabruf akzeptiert nur Kraken Futures,
Trade- und Mark-Kerzen, vier Stunden sowie einen ausgerichteten Zeitraum von
höchstens 370 Tagen. Jede Seite wird roh gespeichert, die Pagination muss
vorwärts fortschreiten und Trade- und Mark-Zeitachsen müssen vollständig
übereinstimmen.

Für den Zeitraum 01.01.2026 bis 24.09.2026, 12:00 UTC wurden jeweils 1.599
Trade- und Mark-Kerzen ohne Lücke geladen. Zusammen mit 2023–2025 liegen damit
8.175 geprüfte Vierstundenblöcke vor. Die 2026-Periode ist ab jetzt gesehene
Entwicklungsinformation. Sie darf die bereits laufenden Zukunftstests weder
ersetzen noch nachträglich verändern.

Der Versuch, lückenlose stündliche Funding-Daten ab Januar 2026 abzurufen,
scheiterte an fehlenden Stunden in der öffentlichen Kraken-Reihe. Es wurden
keine Werte ergänzt. Die Diagnose verwendet deshalb dieselbe vorab festgelegte
adverse Funding-Sensitivität wie die ältere Entwicklungsstudie.

Zusätzlich wurde die öffentliche PF_XBTUSD-Historie rückwärts geprüft. Trade-
und Mark-Reihen besitzen erst ab 23.03.2022, 08:00 UTC einen gemeinsamen,
lückenlosen Vierstundenbeginn. Davor fehlen 488 Trade- beziehungsweise 483
Mark-Intervalle, und die ersten Zeitachsen stimmen nicht überein. Diese Werte
wurden nicht ergänzt. Ab dem gemeinsamen Beginn bis Ende 2022 wurden 1.702
weitere Blöcke gesichert. Der gesamte geprüfte Bestand umfasst damit 9.877
Vierstundenblöcke von März 2022 bis September 2026.

## 2022-Crashdiagnose

Mangels lückenloser Regimedaten wurden nur zwei bereits vorhandene preisbasierte
Regeln unverändert geprüft:

| Regel | Kostenfall | Trades | Netto | Profitfaktor | Max. Drawdown | Max. Hebel |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 30-/120-Tage | beobachtetes p95 | 17 | -15,00 USD | 0,77 | 4,28 % | 2x |
| 30-/120-Tage | doppelte Kosten | 17 | -19,92 USD | 0,70 | 4,58 % | 2x |
| 1-/4-Wochen | beobachtetes p95 | 44 | +35,09 USD | 1,19 | 4,71 % | 3x |
| 1-/4-Wochen | doppelte Kosten | 44 | +20,02 USD | 1,11 | 4,77 % | 3x |

Es gab keine Liquidation. Die kurze Regel reagierte im Crashjahr besser, war
aber 2025 schwach. Sie wird deshalb nicht rückwirkend ausgewählt. Das Ergebnis
begründet höchstens eine neue Mehrhorizont-Hypothese für einen späteren,
getrennten Zukunftstest.

## 2026-Diagnose

Die unveränderte regimebestätigte Momentumregel wurde auf den neu geöffneten
2026-Daten mit einem frischen virtuellen Konto von 1.000 USD geprüft:

| Kostenfall | Trades | Netto | Profitfaktor | Max. Drawdown | Max. Hebel |
| --- | ---: | ---: | ---: | ---: | ---: |
| beobachtetes p95 | 18 | +111,83 USD | 2,54 | 4,53 % | 2x |
| doppelte Kosten | 18 | +98,35 USD | 2,32 | 4,79 % | 2x |

Es gab keine Liquidation. Diese Auswertung ist positiv, aber rückblickend. Sie
beweist keine künftige Profitabilität. LONG und SHORT blieben aktiv, weil die
Richtungsergebnisse zwischen 2023, 2024, 2025 und 2026 wechselten und keine
stabile Grundlage zum Abschalten einer Richtung ergaben.

## Neue Ausführungsprüfung

Vor einem späteren PAPER-Einstieg kann der Bot jetzt einen aktuellen Bid-/Ask-
Quote prüfen. Ein Einstieg wird abgelehnt, wenn:

- der Quote älter als 20 Sekunden oder aus der Zukunft ist;
- der Spread über fünf Basispunkten liegt;
- der Mittelpunkt mehr als zehn Basispunkte vom geplanten Einstieg abweicht;
- geschätzte Gebühren, Spread und Slippage zusammen mehr als 25 Prozent des
  geplanten Stop-Abstands verbrauchen.

Die Prüfung berechnet für LONG und SHORT jeweils einen nachteiligen Einstiegs-
und Stop-Fill. Sie ist fail-closed: Fehlen belastbare aktuelle Ausführungsdaten,
darf kein späterer Orderpfad daraus eine Freigabe ableiten. PAPER und LIVE
bleiben bis zum bestandenen Zukunftstest ausgeschaltet.

## Öffentlicher Livemarktzugang

Der neue Einzeltrade-Sammler hat 50.000 eindeutige PF_XBTUSD-Ausführungen aus
knapp sechs Stunden geladen. Der Bestand umfasst 854,1928 BTC beziehungsweise
rund 73,49 Mio. USD Gegenwert, 24.154 Käufer- und 25.846 Verkäufer-Trades sowie
79 separat gekennzeichnete Liquidationsereignisse. Sämtliche 500 Rohseiten und
die fünf normalisierten CSV-Dateien sind per SHA-256 gebunden. Einzelheiten stehen im
[Livemarktbericht](kraken-live-trades-2026-10-06.md).

Eine 15-Minuten-Diagnose fand zwar eine gleichzeitige Korrelation von 0,425
zwischen Volumenungleichgewicht und Rendite, aber nur 0,060 zur Rendite des
nächsten Fensters. Die nächste Richtung wurde in 47,83 Prozent der Fälle
getroffen. Daraus wird kein neuer Entscheidungsfilter abgeleitet.

Im gemeinsamen Zeitraum 08:00–12:00 UTC enthielten die Einzeltrades 92,22 Prozent
des von der getrennten Kraken-Analytics gemeldeten BTC-Volumens. Die Richtung des
Kaufüberhangs stimmte überein, die zeitbasierte Pagination garantiert jedoch
keine vollständige Tickabdeckung an Seitengrenzen. Der Bestand wird deshalb als
Mikrostrukturstichprobe und nicht als lückenloses Marktband verwendet.

Der Abruf bestätigt einen belastbaren öffentlichen Marktlesezugang. Er bestätigt
weder die persönliche Kontoberechtigung noch eine erzielbare reale Ausführung.
Der persönliche Nur-Lese-Nachweis benötigt weiterhin einen lokal gesetzten,
eng begrenzten Kraken-Schlüssel.
