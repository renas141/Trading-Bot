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
