# PF_XBTUSD-Echtzeit-PAPER

Der Echtzeit-Paperbeobachter liest ausschließlich öffentliche Kraken-Futures-Daten
und sendet keine Orders. Jeder Aufruf ist begrenzt und endet nach der angegebenen
Zahl von Beobachtungen. Es wird keine geplante Aufgabe und kein Hintergrunddienst
angelegt.

## Aktueller Beobachtungsmodus

Solange die vorab registrierte Strategie Screen und Holdout nicht bestanden hat,
ist `no_trade_waiting_for_validation` fest eingestellt. Damit lassen sich
Datenfrische, Neustart, Prüfsummenkette, Dashboard und Sicherheitsfunktionen mit
echten öffentlichen Quotes prüfen, ohne virtuelle Einstiege zu erzeugen:

```bash
.venv/bin/python -m app.derivatives.realtime_paper observe \
  --output data/paper/pf_xbtusd_realtime_observer \
  --cost-candidate data/evidence/perpetual-costs-20260923-evening/cost-candidate.json \
  --cost-summary data/evidence/perpetual-costs-20260923-evening/summary.json \
  --count 1
```

Ein längerer, ausdrücklich gestarteter Lauf kann beispielsweise zehn Beobachtungen
im Minutenabstand erfassen. Der Prozess bleibt währenddessen im Vordergrund:

```bash
.venv/bin/python -m app.derivatives.realtime_paper observe \
  --output data/paper/pf_xbtusd_realtime_observer \
  --cost-candidate data/evidence/perpetual-costs-20260923-evening/cost-candidate.json \
  --cost-summary data/evidence/perpetual-costs-20260923-evening/summary.json \
  --count 10 --interval 60
```

## Sicherheitsmodell

- Aktuelles Bid und Ask, verfügbare Größe, Markpreis, Indexpreis und Börsenzeit
  stammen aus Krakens öffentlichem Futures-Ticker. Der bereits beobachtete
  Spread wird deshalb nicht ein zweites Mal berechnet.
- Die öffentliche Analytics-Reihe liefert die geschätzte Ausführungstiefe für
  1.000, 10.000, 100.000 und 1.000.000 USD. Ihre nachteiligen Slippage-Verhältnisse
  werden an das aktuelle Bid und Ask angelegt; die benötigte Stufe muss für die
  Positionsgröße vorhanden sein. Die kalibrierte p95-Slippage bleibt dabei die
  Mindestannahme, falls die aktuelle Tiefenschätzung günstiger ausfällt.
- Quote, lokale Abrufdauer und Signal besitzen feste Altersgrenzen. Alte oder
  zukünftige Daten verändern das virtuelle Konto nicht.
- Jeder Quote-Beleg enthält die öffentlichen Rohantworten und SHA-256-Prüfsummen.
  Ereignisse bilden eine fortlaufende Prüfsummenkette; doppelte Quotes werden
  nicht erneut verarbeitet.
- Tagesverlust, Gesamtdrawdown, Stop, Margin, Funding und maximal 10x Hebel werden
  gespeichert. Die Risikoprüfung wählt den kleinsten nötigen Hebel.
- Liquidationsschwelle, offener Gewinn/Verlust und Funding verwenden den
  aktuellen Kraken-Markpreis. Schutzstopps verwenden für LONG das aktuelle Bid
  und für SHORT das aktuelle Ask. Bereits gezahltes oder erhaltenes Funding und
  die Liquidationsgebühr verschieben die laufend neu berechnete Schwelle.
- Ein exklusives Dateischloss verhindert zwei gleichzeitige Schreiber.
- LIVE bleibt fest deaktiviert. Das Modul besitzt weder Zugangsdaten noch einen
  privaten Order-Endpunkt.

Jedes Ereignis speichert die vollständigen öffentlichen Ticker- und
Analytics-Rohantworten mit Prüfsummen. Der Ticker ist eine begrenzte REST-
Momentaufnahme und kein lückenloser WebSocket-Feed. Reale Liquidation und Fills
können zwischen zwei Abrufen eintreten; der Lauf bleibt deshalb eine
PAPER-Simulation. Kraken dokumentiert die verwendeten Tiefenreihen unter
[Market Analytics](https://docs.kraken.com/api/docs/futures-api/charts/market-analytics);
für historische Mark-Kerzen steht der öffentliche
[Market-Candles-Endpunkt](https://docs.kraken.com/api/docs/futures-api/charts/candles)
zur Verfügung.

## Manueller Kill Switch

Der Kill Switch sperrt neue virtuelle Einstiege. Schutzschließungen bleiben
zulässig:

```bash
.venv/bin/python -m app.derivatives.realtime_paper halt \
  --output data/paper/pf_xbtusd_realtime_observer
```

Die ausdrückliche Wiederfreigabe lautet:

```bash
.venv/bin/python -m app.derivatives.realtime_paper resume \
  --output data/paper/pf_xbtusd_realtime_observer
```

## Spätere Kandidatenaktivierung

Dieser Befehl funktioniert nur mit unverändertem, bestandenem Screen und Holdout.
Er verwendet einen eigenen Ausgabeordner und übernimmt kein virtuelles Ergebnis
aus der Beobachtungsphase:

```bash
.venv/bin/python -m app.derivatives.realtime_paper activate-candidate \
  --output data/paper/pf_xbtusd_realtime_candidate \
  --forward-root data/forward/pf_xbtusd \
  --protocol data/research/perpetual_funding_aware_forward_20261003_v2/protocol.json \
  --cost-candidate data/evidence/perpetual-costs-20260923-evening/cost-candidate.json \
  --cost-summary data/evidence/perpetual-costs-20260923-evening/summary.json \
  --count 1
```

Eine frische, abgeschlossene Vierstundenkerze kann höchstens einmal ein Signal
erzeugen. Verpasste Kerzen werden nicht nachträglich als Einstiege ausgeführt.
Funding aus neuen verifizierten Paketen wird getrennt verbucht. Nach 42 gehaltenen
Vierstundenblöcken schließt die PAPER-Position beim nächsten beobachteten Quote.
