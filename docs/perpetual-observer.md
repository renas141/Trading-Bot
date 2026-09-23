# Öffentliche Perpetual-Kostenbeobachtung

Der Beobachter liest ausschließlich Krakens öffentliche Market-Analytics für den
linearen Bitcoin-Perpetual `PF_XBTUSD`. Er verwendet keine Zugangsdaten, greift
nicht auf ein Konto zu und besitzt keinen Orderpfad.

Pro Versuch werden drei zusammengehörige Reihen gelesen:

- bester Geld- und Briefkurs für den Spread,
- geschätzte durchschnittliche Ausführungspreise auf beiden Seiten für
  1.000, 10.000, 100.000 und 1.000.000 USD,
- der vorzeichenbehaftete relative Funding-Schlusswert des gleichen
  Minutenintervalls. Ein positiver Wert bedeutet, dass LONG an SHORT zahlt.

Der Beobachter wählt nur den jüngsten Zeitstempel, der in allen drei Antworten
vorhanden ist. Kraken liefert Spread und Slippage mit Sekunden-, Funding aber mit
Millisekunden-Zeitstempeln; beide Formate werden getrennt geprüft. Teilantworten,
unpassende Reihenlängen, gekreuzte Preise, günstig statt nachteilig ausgewiesene
Slippage und zukünftige Zeitstempel werden abgelehnt.

## Messgrößen

Die Spread-Basispunkte werden relativ zum Mittelpunkt berechnet. Die Slippage
wird vom jeweiligen besten ausführbaren Rand aus gemessen:

- Kauf: `(geschätzter Kaufpreis − bester Briefkurs) / bester Briefkurs`
- Verkauf: `(bester Geldkurs − geschätzter Verkaufspreis) / bester Geldkurs`

Damit bleibt der Spread separat. Für eine spätere Market-Order-Simulation müssen
Gebühr, halber Spread vom Mittelpunkt bis zum Rand und nachteilige Slippage
gemeinsam berücksichtigt werden. Die von Kraken veröffentlichten Schätzpreise
sind keine zugesicherten Fills.

## Begrenzter Lauf und Wiederaufnahme

Ein zweistündiger Lauf mit einer Messung pro Minute kann so gestartet werden; die
Deadline muss zeitzonenbehaftet sein und nach dem geplanten Ende liegen:

```bash
.venv/bin/python -m app.market_data.kraken_perpetual_monitor \
  --output data/evidence/perpetual-costs-20260924 \
  --count 120 \
  --interval 60 \
  --until 2026-09-24T04:00:00+00:00
```

Der Ausgabeordner enthält eine SQLite-Datei und `summary.json`. Nach einem
Abbruch kann exakt derselbe Befehl fortgesetzt werden. Eine geänderte Anzahl,
Deadline oder ein geändertes Intervall verlangt einen neuen Ordner. Eine
Dateisperre verhindert zwei gleichzeitige Sammler im selben Ordner.

Jede erfolgreiche Messung speichert die drei Rohantworten, Abrufadressen,
lokale Anforderungs-/Empfangszeit, Börsenintervall und SHA-256-Prüfsummen. Die
Zusammenfassung prüft diese Belege bei jeder Aktualisierung und meldet außerdem:

- erfolgreiche und fehlgeschlagene Versuche,
- Minimum, Median, 95. Perzentil und Maximum des Spreads,
- dieselben Werte für Kauf-/Verkaufsslippage je Größenstufe,
- die beobachteten vorzeichenbehafteten Funding-Werte,
- maximale Abrufdauer, maximales Alter des Analytics-Intervalls und Messlücken.

Ein echter Ein-Punkt-Funktionstest am 23.09.2026 war erfolgreich. Er maß einen
Spread von rund 0,119 Basispunkten. Die geschätzte zusätzliche Slippage betrug
bei 10.000 USD rund 0,338 Basispunkte beim Kauf und 0,262 beim Verkauf; bei einer
Million USD rund 1,330 beziehungsweise 2,543 Basispunkte. Der veröffentlichte
relative Funding-Wert war positiv bei `0.000004444079166667`. Diese einzelne
Minute bestätigt nur die technische Messkette. Sie ist weder eine typische
Kostenannahme noch ein Profitabilitätsnachweis.

Quelle: [Kraken Futures Market Analytics](https://docs.kraken.com/api/docs/futures-api/charts/market-analytics).

## Freigaberegel

Die Messwerte fließen nicht automatisch in eine Strategie ein. Der getrennte
Kalibrierungsschritt verlangt mindestens 360 erfolgreiche Minuten über wenigstens
sechs Stunden, höchstens 5 % Fehler, höchstens 180 Sekunden Abstand zwischen
erfolgreichen Proben, frische Analytics-Zeitstempel und gültige Rohdatenprüfsummen.
Er verwendet für das zum derzeitigen 1.000-USD-Konto und maximal 10x Hebel passende
10.000-USD-Notional den höheren 95.-Perzentil-Wert aus Kauf und Verkauf. Für die
Funding-Sensitivität wird der betragsmäßig ungünstigste beobachtete Stundenwert
vierfach angesetzt. Gebühren werden absichtlich nicht geraten.

Nach einem vollständig bestandenen Lauf wird nur ein neuer Kostenkandidat erzeugt:

```bash
.venv/bin/python -m app.market_data.perpetual_cost_calibration \
  --summary data/evidence/perpetual-costs-20260924/summary.json \
  --output data/evidence/perpetual-costs-20260924/cost-candidate.json
```

Der Kandidat verändert keinen Backtest und aktiviert weder PAPER noch LIVE. Er
muss anschließend als vorab festgelegte Annahme in einem neuen Replay geprüft
werden. Eine einzelne gute Minute, ein kurzer Lauf oder eine lückenhafte Messung
wird technisch abgelehnt.

Der Derivatekern besitzt dafür getrennte Felder: `spread_bps` enthält den ganzen
beobachteten Geld-/Brief-Spread, `slippage_bps` die zusätzliche nachteilige
Ausführung relativ zum besten Rand und `fee_rate` die separat belegte Gebühr.
Bei jedem Einstieg und Ausstieg wird ein halber Spread plus Slippage gegen die
Position gerechnet. Die Risikoprüfung verwendet exakt dieselbe Kostenformel wie
der simulierte Broker. Dadurch wird der Spread weder vergessen noch doppelt
gezählt.

Vor einem neuen Replay lädt `load_observed_cost_scenario` Kandidat und
Quellzusammenfassung gemeinsam. Es berechnet die gesamte Kalibrierung erneut,
vergleicht die Dateien und ihre SHA-256-Bindung und verlangt eine separat
angegebene Gebührenquelle. Erst dann entstehen `DerivativeSettings` mit getrenntem
Spread, Slippage und Gebühr sowie die nachteilige Funding-Sensitivität. Der Lader
besitzt keinen PAPER- oder LIVE-Pfad.
