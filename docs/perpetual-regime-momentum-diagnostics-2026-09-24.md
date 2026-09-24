# Diagnose des regimebestätigten Momentums

Diese Diagnose verändert den abgeschlossenen Versuch nicht. Sie reproduziert
die Trades aus dem eingefrorenen Protokoll und zerlegt nur den bereits gesehenen
2024/2025-Befund.

## Richtung

| Jahr / Kosten | Long-Trades | Long netto | Short-Trades | Short netto |
| --- | ---: | ---: | ---: | ---: |
| 2024 beobachtet | 10 | +52,75 USD | 14 | −43,34 USD |
| 2024 doppelt | 10 | +46,89 USD | 14 | −45,95 USD |
| 2025 beobachtet | 5 | −37,13 USD | 21 | +37,14 USD |
| 2025 doppelt | 5 | −37,50 USD | 21 | +29,00 USD |

Die profitable Richtung wechselte zwischen den Jahren. Ein nachträglicher
Long-only-Filter würde 2025 verschlechtern, ein Short-only-Filter 2024. Die
Diagnose begründet daher keinen stabilen Richtungsfilter.

## Ausstiege

| Jahr / Kosten | Stop-Trades | Stop netto | Zeit-Ausstiege | Zeit-Ausstieg netto |
| --- | ---: | ---: | ---: | ---: |
| 2024 beobachtet | 10 | −102,14 USD | 13 | +110,32 USD |
| 2024 doppelt | 10 | −102,01 USD | 13 | +102,02 USD |
| 2025 beobachtet | 13 | −127,34 USD | 13 | +127,35 USD |
| 2025 doppelt | 13 | −126,59 USD | 13 | +118,09 USD |

Der durchschnittliche Trade war 2024 rund 29,8 und 2025 rund 28,5
Vierstundenkerzen offen; der Median lag jeweils bei der maximalen Haltedauer von
42 Kerzen. Die Gewinner aus den Zeit-Ausstiegen glichen die Stop-Verluste 2025
unter normalen Kosten fast centgenau aus. Verdoppelte Kosten reduzierten die
Gewinnerseite ausreichend, um das Jahr negativ zu machen.

Das ist eine fragile Kostenkante, kein belastbarer Edge. Eine kürzere Haltedauer,
ein engerer Stop oder eine Richtungsumschaltung wäre nach Sichtung dieser Zahlen
eine neue, auf gesehenen Daten abgeleitete Hypothese. Der abgeschlossene Versuch
bleibt unverändert und nicht freigegeben.
