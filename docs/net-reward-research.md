# Zweite Forschungshypothese: Nettoziel und Stop-Risiko

Die erste Auswertung zeigte unter anderem Nettoverluste trotz erreichtem Kursziel.
Die zweite Hypothese ergänzt deshalb genau eine Eintrittsregel: Das vorhandene
Ziel muss nach allen modellierten Kosten mindestens den geplanten Nettoverlust
am Stop decken. Mindestverhältnis: **1:1**, vorab gewählt und nicht optimiert.
Das garantiert weder eine ausreichende Trefferquote noch einen Handelsvorteil.

## Unveränderte Signale, zusätzliche Prüfung

Trend, Breakout, Momentum, Volumen, ATR, Stop und ursprüngliches Preisziel bleiben
wie in `trend_breakout 0.1.0`. Nach der gewöhnlichen Risikoprüfung berechnet die
neue Regel am nächsten Kerzen-Open:

- Einstiegskosten = gerundeter Kaufkurs plus Kaufgebühr.
- Nettoziel je BTC = gerundeter Verkaufserlös am Ziel minus Verkaufsgebühr minus Einstiegskosten.
- Stop-Risiko je BTC = Einstiegskosten minus gerundeter Nettoverkaufserlös am Stop.
- Einstieg nur, wenn Nettoziel mindestens Stop-Risiko ist.

Spread und Slippage stecken in beiden simulierten Ausführungskursen. Das Ziel
wird nicht nach außen verschoben, um die Prüfung zu bestehen. Der Broker prüft
die Regel unabhängig erneut. Kurslücken können den späteren Stop-Verlust erhöhen.
Die Regel ist ausschließlich im Forschungs-Backtest verfügbar.

## Vorab festgelegter Vergleich

Untersuchungszeitraum: 01.01.2026 bis 01.04.2026, Ende exklusiv, UTC.
Markt: BTC/EUR Spot, 15 Minuten, 8.640 erwartete Kerzen. Quelle ist das
[offizielle Kraken-OHLCVT-Archiv](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data)
für Q1 2026. Dieser Zeitraum wurde zuvor im lokalen Projekt nicht ausgewertet.
Er liegt vor Q2, dessen Diagnose die neue Regel motiviert hat: ein zusätzlicher
rückblickender Test, kein Vorwärtstest und kein Nachweis statistischer Unabhängigkeit.

Die Qualitätsprüfung nach Abruf fand nur 8.639 Kerzen: 04.02.2026, 11:30–11:45 UTC
fehlt auch in den offiziellen 5-Minuten-Daten. Vor jeder Ergebnisberechnung
wurde deshalb eine dokumentierte Protokolländerung beschlossen. Zwei getrennte
Abschnitte werden ausgewertet: 01.01.–04.02.11:30 (3.310 Kerzen) und
04.02.11:45–01.04. (5.329 Kerzen). Keine Kerze wird ergänzt. Das ursprüngliche
Protokoll bleibt erhalten; sein Prüfsummenverweis steht in der Änderung.

Vier Läufe **je Abschnitt**: ursprüngliche und gefilterte Variante, jeweils mit normalen und
verdoppelten Gebühren, Spread und Slippage. Jedes Konto startet mit 1.000 EUR;
alle bisherigen Risikogrenzen bleiben bestehen. Die ersten 50 Kerzen dienen
der Strategie in jedem Abschnitt als Aufwärmphase. Am Ende des Abschnitts werden
Positionen geschlossen; das folgende Konto startet unabhängig. Ergebnisse werden
nicht zu einem durchgehenden Quartal zusammengesetzt. Keine Parametersuche.

Zwei zusätzliche Vergleichswerte je Kostenfall: Nicht-Handeln ohne Zinsen und
Kaufen-und-Halten vom ersten Open bis zum letzten Close des jeweiligen Abschnitts. Kaufen-und-Halten
investiert das verfügbare Kapital unter derselben Gebühren- und Rundungsannahme,
hat aber keine Schutzstops oder Verlustlimits und umfasst auch die Aufwärmphase.
Die Kapitalbindung und Risiken unterscheiden sich daher von den Strategieläufen.

Die Hypothese besteht die vorab festgelegte Sichtung nur, wenn die gefilterte
Variante in **beiden Abschnitten und beiden Kostenfällen** alle folgenden Punkte erfüllt:

1. Positiver Nettogewinn.
2. Höherer Nettogewinn als die ursprüngliche Variante.
3. Mindestens 30 ausgeführte Trades.
4. Beobachteter maximaler Drawdown unter 10 %.

Die 30 Trades sind eine feste Arbeitskonvention, kein Signifikanznachweis. Auch
ein Bestehen wäre nur ein Anlass für weitere Prüfung, keine Freigabe für PAPER
oder LIVE. Weniger Verlust bei null Trades zählt nicht als Erfolg.

## Reproduzierbarer Ablauf

Der ursprüngliche Plan wurde vor dem Datenabruf unter
`data/research/net_reward_2026q1_v1/protocol.json` eingefroren. Wegen der nachgewiesenen
Datenlücke startet dieses Protokoll keinen Lauf. Die Daten bleiben als unvollständig
gekennzeichnet; nur der neue Forschungsablauf akzeptiert die genau dokumentierte
Lücke und prüft jeden verwendeten Abschnitt erneut auf Vollständigkeit.

Änderung einfrieren und danach auswerten (Ausgabeordner müssen neu sein):

```bash
python -m backtesting.net_reward_research freeze \
  --amend-from data/research/net_reward_2026q1_v1/protocol.json \
  --dataset data/datasets/kraken_btc_eur_15m_2026q1 \
  --output data/research/net_reward_2026q1_segments_v2
python -m backtesting.net_reward_research evaluate \
  --protocol data/research/net_reward_2026q1_segments_v2/protocol.json \
  --dataset data/datasets/kraken_btc_eur_15m_2026q1
```

Das Protokoll enthält Parameter, beide vollständigen Konfigurationen, Python-Version
und Code-Prüfsummen. Die Auswertung bindet vor dem ersten Lauf die geprüften Daten
mit Manifest- und Candle-Prüfsummen. Abweichender Code, andere Zeiträume, ältere
Downloads oder bereits vorhandene Ausgaben werden abgelehnt. Ein abgebrochener
Lauf bleibt sichtbar und wird nicht automatisch überschrieben.

Alle Ergebnisse und Ablehnungsgründe landen unter `evaluation/`; die vollständigen
Signale, Trades und Equity-Verläufe stehen in der separaten Forschungsdatenbank.
Nach der Auswertung gilt auch Q1 als gesehen. Die ursprünglichen Q2-Artefakte
bleiben als abgeschlossener Versuch erhalten.

## Ergebnis der ersten Auswertung

Die acht Simulationen sind abgeschlossen. Die Hypothese besteht die vorab
festgelegten Kriterien nicht. Die Werte beziehen sich jeweils auf ein eigenes
Konto mit 1.000 EUR und dürfen nicht als durchgehende Quartalsrendite addiert werden.

| Abschnitt | Kosten | Bisherige Variante EUR | Nettoziel-Filter EUR | Gefilterte Trades | Kaufen-und-Halten EUR |
| --- | --- | ---: | ---: | ---: | ---: |
| Vor der Lücke | normal | −100,00 | −10,00 | 1 | −143,18 |
| Vor der Lücke | doppelt | −100,00 | 0,00 | 0 | −149,32 |
| Nach der Lücke | normal | −90,91 | −29,70 | 5 | −89,80 |
| Nach der Lücke | doppelt | −95,38 | 0,00 | 0 | −96,33 |

Nicht-Handeln ergibt jeweils 0 EUR. Der Filter verhindert viele unter den
Kostenannahmen unattraktive Einstiege, erzeugt aber keinen positiven Nettobefund.
Bei normalen Kosten verbleiben insgesamt nur sechs Trades auf zwei unabhängigen
Konten. Bei doppelten Kosten handelt die Variante überhaupt nicht. Das geringere
Verlustniveau ist deshalb kein Nachweis einer profitablen Strategie.

Alle 76 Trades der acht Läufe wurden nachträglich gegen gespeicherte Fills,
Gebühren, Nettoergebnisse und Abschnittsgrenzen abgeglichen. Alle sechs gefilterten
Einstiege erfüllten das Netto-Chance-Risiko-Verhältnis von mindestens 1:1.
Die ursprünglichen Q2-Artefakte und deren damaliger Anwendungscode sind unverändert.

Ausführlicher lokaler Bericht:
`data/research/net_reward_2026q1_segments_v2/evaluation/report.md`.
Exakte Werte, Benchmark-Trades und Prüfkriterien stehen daneben in `results.json`.
Die ursprünglichen Signalbedingungen wurden nicht angepasst. Q1 und Q2 sind nun
beide gesehen; weitere Änderungen benötigen ein neues vorab festgelegtes Protokoll
und weitere bislang ungenutzte Daten. PAPER bleibt beim bisherigen inaktiven Standard.
