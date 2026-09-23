# Perpetual- und Hebelforschung, 23.09.2026

## Ergebnis

Der Bot besitzt jetzt ein getrenntes, ausschließlich simuliertes Modell für den linearen Bitcoin-Perpetual `PF_XBTUSD`. Es unterstützt LONG und SHORT, Funding, Initial- und Maintenance-Margin, Mark-Preis-Liquidation, Liquidationsgebühr, Stop-/Zielausführung und eine dynamische Hebelwahl von 1x bis höchstens 10x. Das Modell sendet keine Orders und enthält keine private Börsenanbindung.

Eine profitable Strategie ist weiterhin nicht nachgewiesen. Die zunächst positive Long-only-Entwicklung scheiterte in der genau einmal ausgeführten 2025-Holdout-Prüfung. Sie wurde deshalb nicht für PAPER oder LIVE aktiviert.

## Hebel- und Risikoregel

Der Hebel ist keine Gewinnquelle. Die Positionsmenge wird zuerst aus maximal 1 % Kontorisiko, Stop-Abstand, Ein-/Ausstiegsgebühr und Slippage berechnet. Anschließend wählt der Risk Manager den kleinsten Hebel, mit dem die festgelegte Margin-Zuteilung ausreicht. Der Stop muss vor dem modellierten Liquidationspreis plus 2 % zusätzlichem Preisabstand liegen. Andernfalls wird die Position verkleinert oder abgelehnt.

Die absolute Obergrenze ist 10x. In den abgeschlossenen Studien wurden höchstens 3x in 2023/2024 und 5x im 2025-Holdout benötigt. Es gab keine Liquidation. Das zeigt nur, dass die Schutzlogik im Replay wirkte; es belegt keinen künftigen Schutz bei Kurslücken oder Börsenausfällen.

## Daten und Kosten

Die Daten stammen aus Krakens öffentlicher Futures-Charts-API. Trade- und Mark-Preis wurden getrennt gespeichert und auf dieselbe lückenlose Vierstunden-Zeitachse geprüft:

| Zeitraum | Trade-Kerzen | Mark-Kerzen | Lücken |
| --- | ---: | ---: | ---: |
| 2023–2024 Entwicklung | 4.386 | 4.386 | 0 |
| 2025 Holdout | 2.190 | 2.190 | 0 |

Die normale Simulation verwendet 0,05 % Taker-Gebühr je Seite und 5 Basispunkte Slippage. Der Stressfall verwendet 0,10 % und 10 Basispunkte. Weil die öffentliche Funding-Historie für diese Jahre nicht vollständig verfügbar war, wurde Funding nie mit null angesetzt: normal wurden nachteilig 0,005 % pro vier Stunden berechnet, im Stress 0,02 %. Dies sind Sensitivitäten und keine rekonstruierten historischen Funding-Zahlungen.

Offizielle Quellen:

- [Kraken Futures Candle API](https://docs.kraken.com/api/docs/futures-api/charts/candles)
- [Kraken Derivatives Gebühren](https://support.kraken.com/articles/360048917612-fee-schedule)
- [Kraken Derivate-Margin und maximaler Hebel](https://support.kraken.com/de/articles/360022632452-derivatives-margin-schedule-maximum-leverage)
- [Kraken Derivatives Teilnahmevoraussetzungen für EWR-Kunden](https://support.kraken.com/de/articles/derivatives-eligibility-requirements-eea)

Der am 23.09.2026 gesicherte öffentliche Instrumentkatalog weist für `PF_XBTUSD` bei der europäischen Retail-Staffel am kleinsten Notional eine Initial Margin von 10 % und Maintenance Margin von 5 % aus. Daraus folgt in dieser Staffel maximal 10x. Die lokale Rohantwort hat SHA-256 `b0386bd584c7485cc2175693e743737083236da1a27089b1873647c836102b85`. Kraken kann Marginpläne ändern; außerdem muss ein EWR-Konto vollständig verifiziert sein und die individuelle Eignungsprüfung bestehen. Das Programm behauptet keine Kontoberechtigung.

## Forschungsfolge

### v1: symmetrischer Regime-Ausbruch

Die vorab festgelegte Regel kombinierte 120-Kerzen-Ausbruch, 600-Kerzen-Trend und dessen Steigung, Effizienz-, ATR- und Volumenfilter, 3-ATR-Stop und 3R-Ziel. Sie durfte LONG und SHORT handeln.

| Jahr | Normal | Stress | Trades | Befund |
| --- | ---: | ---: | ---: | --- |
| 2023 | +52,05 USD | +39,68 USD | 4 | positiv, aber normale Mindestzahl verfehlt |
| 2024 | −16,82 USD | −27,44 USD | 9 | negativ |

Das Gate scheiterte. 2025 wurde für v1 nicht geöffnet.

### v2: dateninformierter Long-only-Filter

Nach dem v1-Fehlschlag wurde als neue, ausdrücklich ergebnisinformierte Hypothese ausschließlich die SHORT-Seite unterdrückt. Alle übrigen Parameter, Kosten, Funding- und Risikoregeln blieben unverändert.

| Jahr | Normal | Stress | Trades | Max. Drawdown Stress |
| --- | ---: | ---: | ---: | ---: |
| 2023 | +52,05 USD | +39,68 USD | 4 | 2,06 % |
| 2024 | +24,02 USD | +15,52 USD | 5 | 2,88 % |

Das Entwicklungstor bestand. Weil die Idee aus bereits gesehenen Ergebnissen entstand, war dies noch keine unabhängige Bestätigung.

### Einmaliger 2025-Holdout

| Fall | Netto | Trades | Gewinner | Profitfaktor | Max. Drawdown | Max. Hebel |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| normal | −19,06 USD | 5 | 1 | 0,568 | 6,33 % | 5x |
| Stress | −34,40 USD | 5 | 1 | 0,371 | 7,06 % | 4x |

Der Holdout scheiterte in beiden Kostenfällen. 2025 gilt nun als gesehen. Eine Regeländerung anhand von 2025 wäre eine neue Entwicklungshypothese und braucht neue, zeitlich spätere Daten für eine unabhängige Prüfung.

## Nachgelagerte Gewinnschutz-Entwicklung

Die Diagnose zeigte zwei spätere Verlusttrades, die zuvor ungefähr +2,58R beziehungsweise +1,89R erreicht hatten. Daraufhin wurden genau zwei kausale Regeln vor der Auswertung festgelegt: Preis-Break-even nach einem abgeschlossenen Schlusskurs über +1R sowie +1R sichern nach einem Schlusskurs über +2R. Ein neuer Stop war immer erst ab der folgenden Kerze aktiv; das Tief der Berechnungskerze wurde nicht rückwirkend verwendet.

| Regel | 2023 Stress | 2024 Stress | 2025 normal | 2025 Stress | Auswahl |
| --- | ---: | ---: | ---: | ---: | --- |
| unverändertes 3R-Ziel | +39,68 USD | +15,52 USD | −19,06 USD | −34,40 USD | nein |
| Break-even nach +1R | +37,30 USD | +15,52 USD | +1,81 USD | −8,84 USD | nein |
| +1R sichern nach +2R | +46,82 USD | +15,52 USD | +1,72 USD | −9,72 USD | nein |

Beide Regeln verbesserten 2025 deutlich und senkten Funding sowie Drawdown. Keine war jedoch in allen drei Jahren unter normalen und verschärften Annahmen positiv. Das festgelegte Auswahlverfahren lieferte deshalb keinen Kandidaten. 2026 wurde nicht heruntergeladen oder ausgewertet und bleibt für eine spätere, wirklich neue Hypothese verfügbar.

## Brokerentscheidung

Kraken ist derzeit der technisch passendste Kandidat für diese Forschungsstrecke, weil öffentliche Trade-/Mark-Daten, ein linearer BTC/USD-Perpetual, ein dokumentiertes Funding-/Margin-Modell und ein regulierter EWR-Zugangsweg vorhanden sind. Die niedrige Basistakergebühr von 0,05 % löst das Strategieproblem jedoch nicht; der 2025-Holdout blieb selbst damit negativ.

Vor einer privaten PAPER-Anbindung müssen Kontoberechtigung, tatsächlich angezeigter Marginplan, Collateral-Währung, minimale Ordergröße, Funding-Abrechnung und API-Berechtigungen am konkreten Konto geprüft werden. Eine Live-Anbindung ist erst vertretbar, wenn eine neue Strategie auf zeitlich späteren Daten besteht und anschließend über längere Zeit mit echten Quotes und simulierten Fills beobachtet wurde.
