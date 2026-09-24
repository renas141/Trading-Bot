# Regimebestätigtes PF_XBTUSD-Momentum

Stand: 24.09.2026. Ergebnis: **Entwicklungs-Gate nicht bestanden; keine
Handelsfreigabe.**

## Festgelegte Regel

Nach der dokumentierten Exploration von acht Bestätigungskombinationen wurde
genau eine Replay-Regel vor der Ergebnisberechnung eingefroren:

- 7- und 28-Tage-Kursrendite müssen dasselbe Vorzeichen haben.
- Open Interest muss über sieben Tage gestiegen sein.
- der verzögerte aktuelle Aggressor-Fluss und die verzögerte siebentägige
  CVD-Änderung müssen beide in Trendrichtung zeigen.
- Stop: dreifacher 7-Tage-ATR; kein festes Kursziel; spätestens nach sieben
  Tagen schließen; Ausführung frühestens zur nächsten Kerzeneröffnung.
- pro Trade höchstens 1 % Eigenkapitalrisiko und dynamisch der kleinste nötige
  Hebel bis maximal 10x.

Regimewerte erhielten zusätzlich zur abgeschlossenen Analytics-Periode einen
vollen Vierstunden-Sicherheitsabstand. Long/Short-Verhältnis,
Volatilitätsschwellen und Liquidationsvolumen wurden nicht als Filter verwendet.

Das Protokoll wurde um 14:05:36 UTC eingefroren. Sein SHA-256 lautet
`9ee49df96edbed3f7b3bada0f3f4ec42be75a86fe37eaaf8453cda327c42bacf`.
Die Regel war zuvor als Git-Commit `5aefc17` gesichert. Das Ergebnis ist an den
beobachteten achtstündigen Kostenlauf, zwei Kurs- und drei Regimedatensätze sowie
20 Quellcodedateien gebunden.

## Ergebnis auf gesehenen Entwicklungsdaten

Jedes Jahr startet mit 1.000 USD. `observed_p95` verwendet die gemessenen
p95-Ausführungskosten und nachteilige Funding-Sensitivität; der Stressfall
verdoppelt Gebühren, Spread, Slippage und Funding.

| Jahr | Kostenfall | Trades | Netto USD | Profitfaktor | Max. Drawdown | Funding | Max. Hebel |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 ab 31.05. | beobachtetes p95 | 14 | +135,70 | 3,179 | 3,46 % | 2,86 | 3x |
| 2023 ab 31.05. | doppelte Kosten | 14 | +121,30 | 2,898 | 3,46 % | 5,48 | 2x |
| 2024 | beobachtetes p95 | 24 | +9,41 | 1,084 | 7,25 % | 2,86 | 2x |
| 2024 | doppelte Kosten | 24 | +0,94 | 1,008 | 7,47 % | 5,55 | 2x |
| 2025 | beobachtetes p95 | 26 | +0,01 | 1,000 | 5,56 % | 3,08 | 2x |
| 2025 | doppelte Kosten | 26 | **−8,50** | 0,942 | 5,66 % | 5,97 | 2x |

Das vorab festgelegte Gate verlangte in jedem Jahr und beiden Kostenfällen
positiven Nettogewinn, unter 10 % Drawdown, mindestens sechs Trades, keine
Liquidation und höchstens 10x Hebel. Nur `2025/double_cost_stress` scheiterte am
Gewinnkriterium. Die normale 2025-Auswertung lag mit 0,01 USD wirtschaftlich
praktisch bei null. Deshalb wurde kein Kandidat ausgewählt.

Die Ergebnisdatei hat SHA-256
`864c03f88ef63bd47268b45c1a9dd6f271540cd6451c9b4abaf15fcc9f541c10`;
der lokale Abschlussbeleg bindet genau diesen Hash.

## Einordnung

Die Regimebestätigung verbesserte den schwachen 2025-Befund gegenüber der
ungefilterten kurzfristigen Momentum-Regel deutlich, überstand aber den
Kostenstress nicht. Eine weitere Filteränderung auf denselben Jahren würde den
bereits gesehenen Daten folgen und zählt nicht als Reparatur dieses Versuchs.
Die getrennte [Trade-Diagnose](perpetual-regime-momentum-diagnostics-2026-09-24.md)
zeigt zudem, dass die profitable Richtung zwischen 2024 und 2025 wechselte und
die Zeit-Ausstiege 2025 die Stop-Verluste nur vor erhöhten Kosten ausglichen.

2026-PF_XBTUSD-Kursresultate wurden weiterhin weder geladen noch ausgewertet.
Da 2026-Regimeverteilungen bereits bei der technischen Datenprüfung angesehen
wurden, wäre 2026 nur ergebnisblind. Der vollständig blinde Zeitraum für eine
aus diesen Merkmalen abgeleitete Regel beginnt nach dem 24.09.2026. PAPER und
LIVE bleiben gesperrt.
