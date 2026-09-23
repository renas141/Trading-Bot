# Diagnose der ersten Forschungshypothese

Die Diagnose liest die eingefrorene Forschungsdatenbank ausschließlich lesend.
Sie führt keine Simulation erneut aus und verändert weder Strategie noch Risiko-
oder Kostenparameter. Alle 71 ausgeführten Trades der vier ursprünglichen Läufe
wurden mit ihren Freigaben, Signalgründen, Kursdaten und Ergebnissen abgeglichen.

## Befund unter den ursprünglichen Kostenannahmen

| Zeitraum / Kosten | Trades | Kursbewegung brutto EUR | Gesamtkosten EUR | Netto EUR |
| --- | ---: | ---: | ---: | ---: |
| April–Mai / base | 24 | 24,45 | 124,45 | −100,00 |
| April–Mai / double_costs | 18 | 10,82 | 110,82 | −100,00 |
| Juni / base | 16 | −23,26 | 76,74 | −100,00 |
| Juni / double_costs | 13 | −14,62 | 85,38 | −100,00 |

Gesamtkosten enthalten beide Gebühren, Spread, Slippage und Preisrundung.
Die Werte sind gerundet. Die Bruttozerlegung hält Mengen und Trade-Auswahl fest;
sie ist **kein Backtest ohne Kosten**. Andere Kosten verändern auch Mengen,
Freigaben und den Zeitpunkt, an dem das Risikobudget praktisch aufgebraucht ist.
Deshalb können die Stressläufe trotz höherer Kosten pro Transaktion insgesamt
weniger Kosten aufweisen. Die vier Läufe sind keine identischen Portfolios.

Bei normalen Kosten erreichten im Entwicklungszeitraum zehn Trades das Ziel,
zwei davon mit Nettoverlust; im Juni vier Trades, einer davon mit Nettoverlust.
Schon beim Einstieg war das Ziel nach Kosten bei fünf von 24 beziehungsweise
drei von 16 Trades nicht profitabel. Bei doppelten Kosten waren es 13 von 18
beziehungsweise zehn von 13. Das Preisziel von zweimal dem ATR-Stop-Abstand ist
kein Netto-Chance-Risiko-Verhältnis von 2:1. Das Journal weist beides getrennt aus.

Im Juni endeten bei normalen Kosten zwölf von 16 Trades am Stop. Auch das
Bruttoergebnis dieser ausgeführten Trades war negativ. Damit erklären Gebühren
allein die Schwäche nicht. Daraus lässt sich nicht ableiten, welcher einzelne
Indikator verantwortlich ist oder welche neue Regel künftig profitabel wäre.

Die letzten Ausstiege erfolgten bei normalen Kosten am 17. April beziehungsweise
14. Juni, bei doppelten Kosten am 14. April beziehungsweise 13. Juni (UTC).
Danach wurden sämtliche weiteren LONG-Signale wegen zu kleiner zulässiger
Positionsgröße abgelehnt: 105, 39, 121 beziehungsweise 44. Das verbleibende
Drawdown-Budget lag je Lauf unter 0,00001 EUR. Der harte Drawdown-Schalter wurde
dadurch knapp nicht ausgelöst; die Mindestgröße verhinderte weitere Einstiege.

## Reproduzieren

Im Projektordner mit aktivierter Python-Umgebung:

```bash
python -m backtesting.diagnostics \
  --research data/research/trend_breakout_2026q2_v1 \
  --dataset data/datasets/kraken_btc_eur_15m_2026q2 \
  --output data/diagnostics/trend_breakout_2026q2_reproduction
```

Nach Paketinstallation ist derselbe Aufruf als `trading-diagnose` verfügbar.
Der Ausgabeordner muss neu sein. Die erste Auswertung liegt lokal unter
`data/diagnostics/trend_breakout_2026q2_v1/` und enthält:

- `report.md`: Kostenzerlegung, Zielausstiege, Ablehnungen und verbleibendes Budget.
- `trades.csv`: Jeder ausgeführte Trade mit Kursreferenzen, tatsächlichen Fills,
  Kosten, Nettoergebnis, Ziel-Nettoergebnis beim Einstieg und Signalgründen.
- `summary.json`: Exakte Summen und Prüfsummen der drei Forschungsquelldateien.

Die Diagnose unterstützt das gespeicherte Modell `cash-long-next-bar-v1` und
den ursprünglichen Forschungsablauf mit 15-Minuten-Kerzen. Stops mit Kurslücke
verwenden den Eröffnungskurs; Zielausstiege bleiben auf den Zielkurs begrenzt.
Intrabar-Ausstiege verwenden die dokumentierte Modellkonvention und stellen
keine tickgenaue Haltedauer dar. Netto-Chance-Risiko beim Einstieg verwendet
den geplanten Stop ohne spätere Kurslücke. Ein Gap kann den Stop-Verlust erhöhen.

Die Prüfungen kontrollieren Herkunft, gespeicherte Fills, Gebühren, Freigaben,
Trade-Summen und Abschlusskapital. Sie sind eine Konsistenzprüfung der lokalen
Artefakte, keine unabhängige Echtheitsbestätigung der Marktquelle.

Diese Diagnose bestätigt die Hypothese nicht. Der Juni bleibt ein bereits
gesehener Testzeitraum. Eine neue Hypothese muss vorab festgelegt und auf einem
anderen, bislang ungenutzten Zeitraum geprüft werden. Kostenbewertung und
wirtschaftliche Sinnhaftigkeit des Nettoziels sind dabei getrennt von der
Frage zu untersuchen, ob die Einstiegssignale überhaupt einen Vorteil liefern.
