# Laufende PF_XBTUSD-Forward-Sammlung

Start: 24.09.2026. Die Sammlung liest ausschließlich öffentliche Kraken-Daten,
sendet keine Orders und aktiviert weder PAPER noch LIVE.

## Inhalt je Vierstundenblock

Jeder abgeschlossene UTC-Block wird in einem neuen, unveränderlichen Verzeichnis
gespeichert:

- genau eine Trade- und eine Mark-Kerze für `PF_XBTUSD`;
- Open Interest, Aggressor-Differenz, Liquidationsvolumen, rollende Volatilität,
  Long/Short-Verhältnis, Kauf-/Verkaufsvolumen und CVD;
- vier stündliche, vorzeichenbehaftete Funding-Werte;
- ein öffentlicher Spread-/Slippage-Snapshot zum tatsächlichen Sammelzeitpunkt;
- sämtliche Rohantworten, normalisierte Dateien, Qualitätsberichte und
  SHA-256-Prüfsummen.

Der Sammler folgt keinen Weiterleitungen und lässt für Preise nur den festen
Kraken-Host, `PF_XBTUSD`, Trade/Mark, vier Stunden und genau einen abgeschlossenen
Block zu. Regime- und Funding-Komponenten verwenden ihre eigenen festen
Allowlisten. Ein unvollständiger Block wird vollständig verworfen. Bei einem
erneuten Lauf werden vorhandene Pakete geprüft und nicht erneut abgerufen.

Der Spread-/Slippage-Wert ist ein aktueller Snapshot. Bei einer verspäteten
Nachholung älterer Kerzen wird er ausdrücklich nicht als historischer Wert des
nachgeholten Blocks ausgegeben.

## Erster Block

Zeitraum: 24.09.2026 08:00 bis 12:00 UTC, Ende exklusiv.

- 23 gebundene Dateien, Bundle-SHA-256:
  `af0a6e31c9139ce6ecd11d36416134ec99289b5bd1966db35583b6f9eeca440b`;
- Trade OHLC: 84.504 / 84.621 / 82.834 / 83.470 USD;
- Mark-Schluss: 83.461,9015 USD;
- Funding-Summe über vier Stunden: `0.000005222455833334`;
- Regime: Open Interest 2.192,3104, Aggressor-Differenz +243,8232,
  Liquidationsvolumen 1,8725 und Long/Short-Verhältnis 0,56;
- Kosten-Snapshot um 14:27 UTC: Spread 0,1183 Basispunkte, geschätzte
  10.000-USD-Kaufslippage 0,2962 Basispunkte und Verkaufsslippage 0,0
  Basispunkte.

Der Kosten-Snapshot entstand rund zweieinhalb Stunden nach dem Blockende und
belegt nur den Sammelzeitpunkt. Er wird nicht zur nachträglichen Bewertung der
Kerzenausführung verwendet.

## Verwendung

Neue Blöcke werden unter `data/forward/pf_xbtusd` gespeichert; dieser lokale
Evidenzbereich ist von Git ausgeschlossen. Der Sammler kann verpasste Blöcke
chronologisch nachholen, höchstens 42 pro Lauf. Strategien dürfen erst nach einer
vorab festgelegten Mindestdauer auf die neuen Outcomes zugreifen. Bis dahin
dienen die Pakete nur dem Aufbau eines unabhängigen Forward-Zeitraums.
