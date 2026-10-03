# Funding-bewusstes PF_XBTUSD-Forward-Protokoll

Stand und fester Ergebnisschnitt: **03.10.2026, 12:00 UTC**. Alle bis dahin
gesammelten Vierstundenblöcke sind von der Performance-Auswertung ausgeschlossen.
Sie dienen nur als Integritätsnachweis der Sammlung. PAPER und LIVE bleiben aus.

## Hypothese

Der bisher beste Regime-Kandidat kombinierte 7-/28-Tage-Momentum mit steigendem
Open Interest und übereinstimmendem Handelsfluss. Er war 2025 bei normalen Kosten
wirtschaftlich ungefähr neutral und verlor im doppelten Kostenstress. Die neue
Regel prüft deshalb eine eigenständige, vor der Forward-Auswertung festgelegte
Hypothese:

- 2- und 7-Tage-Kursrendite müssen dasselbe Vorzeichen haben;
- Open Interest muss über sieben Tage gestiegen sein;
- der mit Sicherheitsverzögerung verfügbare Aggressor-Fluss und die siebentägige
  CVD-Änderung müssen in Kursrichtung zeigen;
- die im gerade abgeschlossenen Vierstundenblock in Handelsrichtung anfallende
  Funding-Belastung darf nicht höher sein als ihr Mittel der vorherigen 24 Stunden;
- anfänglicher Stop im Abstand des dreifachen 7-Tage-ATR;
- Schließung spätestens nach sieben Tagen, Entscheidung am Schluss und Ausführung
  frühestens am nächsten Open;
- höchstens 1 % Kontorisiko und der kleinste notwendige Hebel bis maximal 10x.

Der Funding-Filter verwendet keinen aus Kursresultaten angepassten Schwellenwert.
Er prüft lediglich, ob der bereits abgeschlossene Funding-Druck zunimmt. Funding
ist bei Perpetuals eine signierte Zahlung zwischen Long und Short und kann neben
seiner direkten Kostenwirkung auch Marktspannung abbilden. Forschung beschreibt
sowohl Funding-/Basis- und Preis-Volumen-Faktoren als systematische Treiber als
auch Grenzen der stabilisierenden Wirkung bei Liquidationen und gebundenem Kapital:

- [Anatomy of Cryptocurrency Perpetual Futures Returns](https://papers.ssrn.com/sol3/papers.cfm?abstractid=6365329)
- [A Shared Template Without Shared Feedback](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6185958)
- [Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888)

Diese Quellen begründen die Merkmalsfamilie, belegen aber nicht die konkrete Regel
und garantieren keinen Handelsvorteil.

## Zwei getrennte Stufen

### Forward-Screen

- 180 neue Vierstundenblöcke ab dem Schnittpunkt, entsprechend 30 Tagen;
- die ersten 43 Blöcke sind ausschließlich Warm-up;
- eigenes Konto mit 1.000 USD je Kostenfall;
- mindestens vier geschlossene Trades;
- positiver Nettogewinn, Profitfaktor mindestens 1,10, Drawdown unter 8 %,
  keine Liquidation und höchstens 10x Hebel;
- alle Bedingungen müssen mit beobachteten p95-Ausführungskosten und im Fall mit
  verdoppelten Gebühren, Spread, Slippage und Funding bestehen.

Das erwartete Ende liegt am **02.11.2026, 12:00 UTC**. Ein Erfolg öffnet nur den
vorab festgelegten Holdout; er aktiviert kein PAPER.

### Holdout

- weitere 360 Blöcke beziehungsweise 60 Tage ohne Regeländerung;
- frisches Konto je Kostenfall und 43 unmittelbar vorhergehende Warm-up-Blöcke;
- mindestens acht geschlossene Trades;
- positiver Nettogewinn, Profitfaktor mindestens 1,20, Drawdown unter 10 %,
  keine Liquidation und höchstens 10x Hebel;
- wiederum Bestehen in beiden Kostenfällen.

Der Gesamtzeitraum von 540 Blöcken endet voraussichtlich am
**01.01.2027, 12:00 UTC**. Nur ein vollständiges Bestehen macht die unveränderte
Regel zum Kandidaten für einen dauerhaften simulierten Kraken-PAPER-Lauf.

## Integrität und Ausführung

Das lokale Protokoll bindet Regel, Parameter, Kostenquelle und sämtlichen
Auswertungscode per SHA-256. Die Auswertung lädt nur vollständige, lückenlose
Bundles nach dem Schnittpunkt. Sie verwendet echte signierte Stunden-Fundingwerte,
Trade- und Mark-Kerzen sowie die bereits konservativ verzögerten Regimedaten.

Eingefrorener lokaler Protokollpfad:
`data/research/perpetual_funding_aware_forward_20261003_v2/protocol.json`.
SHA-256: `eecb5b59e6b9db709aa05a1d9fcd3ca626a7e098014cce4860af4c45bb4483fe`.
Der Beleg schließt 55 zuvor gesammelte Blöcke bis zum Ergebnisschnitt ausdrücklich
von der Performance-Auswertung aus.

Der Screen muss mit gültigem Abschlussbeleg bestehen, bevor der Holdout überhaupt
gelesen werden darf. Ein Fehlschlag beendet die Hypothese. Parameteränderungen
würden eine neue Regel und einen neuen zukünftigen Zeitraum erfordern.

## Gesperrter Forward-Paperbetrieb

Die Software für die nachgelagerte Shadow-PAPER-Stufe ist fertig. Ihr Status lässt
sich bereits jetzt lesen, ohne Screen- oder Holdout-Ergebnisse vorzeitig zu öffnen:

```bash
.venv/bin/python -m app.derivatives.forward_paper status \
  --protocol data/research/perpetual_funding_aware_forward_20261003_v2/protocol.json
```

Der eigentliche Start verlangt gültige Abschlussbelege für **beide** Stufen. Er
prüft zusätzlich die Prüfsummen des Protokolls, der Kostenannahmen, der Ergebnisse
und sämtlicher verwendeter Forward-Pakete. Fehlt eine Bedingung oder wurde eine
Datei verändert, endet der Aufruf ohne Handelssimulation:

```bash
.venv/bin/python -m app.derivatives.forward_paper run \
  --output data/paper/pf_xbtusd_funding_aware_v2 \
  --forward-root data/forward/pf_xbtusd \
  --protocol data/research/perpetual_funding_aware_forward_20261003_v2/protocol.json \
  --cost-candidate data/evidence/perpetual-costs-20260923-evening/cost-candidate.json \
  --cost-summary data/evidence/perpetual-costs-20260923-evening/summary.json
```

Nach einer Freigabe beginnt der Lauf mit einem frischen virtuellen Konto. Er
übernimmt keine Gewinne aus Screen oder Holdout. Pro Block werden LONG/SHORT,
Funding, Mark-Kurs, Stop, Liquidation, maximal sieben Tage Haltedauer, Tagesverlust
und Drawdown verarbeitet. Der Risikomanager lässt höchstens 10x zu und wählt den
kleinsten Hebel, der für die risikobasierte Position nötig ist. Jeder Zustand ist
über eine Ereignis-Prüfsummenkette wiederherstellbar; ein zweiter Prozess wird per
Dateisperre abgewiesen.

Das ist bewusst eine **Forward-Shadow-Simulation**. Die Eingangsentscheidung ist
zeitlich kausal und verwendet den nächsten Vierstunden-Open, das fertige Paket wird
aber erst nach Abschluss dieses Blocks archiviert. Damit prüft der Lauf Strategie,
Kosten-, Margin- und Wiederanlauflogik auf neuen Daten. Er misst noch keine reale
Orderlatenz und sendet niemals Orders. Eine private Kraken-Anbindung bleibt separat
und LIVE bleibt technisch gesperrt.
