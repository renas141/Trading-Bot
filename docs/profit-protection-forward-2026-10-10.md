# Zukunftstest: adaptiver Einstieg mit kausalem Gewinnschutz

Der dritte PF_XBTUSD-Kandidat wurde am 10.10.2026 um 13:33 UTC gebunden. Sein
Forward-Zeitraum beginnt am selben Tag um 16:00 UTC. Alle früheren Daten gelten
als gesehenes Warm-up und dürfen seine Profitabilität nicht bestätigen.

## Hypothese

Der Einstieg entspricht unverändert dem adaptiven v2-Kandidaten: Zwei- und
Sieben-Tage-Momentum müssen dieselbe Richtung zeigen, mindestens drei von vier
verzögerten Regime- und Funding-Signalen müssen bestätigen. Drei Bestätigungen
verwenden 0,5 Prozent normales Stop-Risiko, vier Bestätigungen 1,25 Prozent. Der
Stressmanager darf Größe und Hebel reduzieren; 10x bleibt die harte Obergrenze.

Neu ist ausschließlich der Gewinnschutz. Schließt eine vollständig abgeschlossene
Vierstundenkerze mindestens 1R im Gewinn, wird der Stop auf den Einstieg gezogen.
Der neue Stop gilt erst ab der nächsten Kerze. Tief oder Hoch der auslösenden
Kerze dürfen ihn nicht rückwirkend treffen. Eine Kurslücke durch den Stop wird
zum ungünstigeren nächsten Eröffnungskurs abgerechnet; ein Stop darf nie wieder
gelockert werden.

## Warum dieser Test getrennt ist

Auf vollständig gesehenen Daten von 2023 bis 2025 reduzierte eine vergleichbare
Break-even-Regel den 2025-Verlust des früheren Long-Bias-Modells im normalen
Kostenfall von rund 19,06 USD Verlust auf 1,81 USD Gewinn. Im doppelten
Kostenstress blieb sie mit rund 8,84 USD Verlust negativ. Das ist eine
Entwicklungsbeobachtung, kein Profitabilitätsnachweis.

Der neue Kandidat wird deshalb unabhängig bewertet. Er darf weder den strikten
Kandidaten vom 03.10. noch den adaptiven v2-Kandidaten vom 05.10. ersetzen oder
retten. Ein Vergleich mit den beiden anderen Kandidaten darf nicht nachträglich
zur Gewinnerauswahl verwendet werden.

## Vorab festgelegte Tore

- Screen: 180 neue Vierstundenblöcke, mindestens sechs Trades je Kostenfall,
  positiver Nettogewinn, Profitfaktor mindestens 1,10, Drawdown unter acht
  Prozent und keine Liquidation. Bei lückenloser Sammlung endet dieser Zeitraum
  frühestens am 09.11.2026 um 16:00 UTC.
- Holdout: weitere 360 Blöcke, mindestens zwölf Trades je Kostenfall,
  positiver Nettogewinn, Profitfaktor mindestens 1,20, Drawdown unter zehn
  Prozent und keine Liquidation. Er darf erst nach bestandenem Screen geöffnet
  werden und wäre frühestens am 08.01.2027 um 16:00 UTC vollständig.
- Beide Stufen rechnen einmal mit beobachtetem p95-Spread und Slippage sowie
  echtem Funding und einmal mit verdoppelten Kosten und Funding-Werten.
- Nur ein bestandener Holdout erlaubt einen eigenen längeren PAPER-Lauf. LIVE
  bleibt gesperrt.

Das lokale Protokoll hat die SHA-256-Prüfsumme
`1779a899a385d253e4f65454da16e56e052f63589545f3a804bc051aa1125c3a`.
