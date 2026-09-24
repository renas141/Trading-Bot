# Duales Zeitreihen-Momentum, 24.09.2026

## Ergebnis

Die neue, vor der Auswertung festgeschriebene Momentum-Regel bestand das
Entwicklungstor nicht. Sie war 2023 und 2024 unter den beobachteten Kosten sowie
unter doppelten Kosten profitabel, verlor aber 2025 in beiden Fällen. Deshalb
wurde kein Kandidat ausgewählt. Die zurückgehaltenen PF_XBTUSD-Kursdaten ab 2026
wurden weder geladen noch ausgewertet. PAPER und LIVE bleiben gesperrt.

| Jahr | Kostenfall | Trades | Netto USD | Profitfaktor | Max. Drawdown | Max. Hebel |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2023 | beobachtetes p95 | 19 | +129,02 | 3,392 | 3,44 % | 2x |
| 2023 | doppelte Kosten | 19 | +115,51 | 3,070 | 3,49 % | 2x |
| 2024 | beobachtetes p95 | 42 | +68,74 | 1,389 | 8,45 % | 1x |
| 2024 | doppelte Kosten | 42 | +55,16 | 1,309 | 8,95 % | 1x |
| 2025 | beobachtetes p95 | 39 | −20,32 | 0,866 | 7,37 % | 2x |
| 2025 | doppelte Kosten | 39 | −31,21 | 0,798 | 7,44 % | 2x |

## Vorab festgelegte Regel

Die Strategie verwendet ausschließlich den eigenen PF_XBTUSD-Preis auf
Vierstundenkerzen:

- LONG, wenn die 30- und 120-Tage-Rendite beide positiv sind;
- SHORT, wenn beide Renditen negativ sind;
- andernfalls HOLD;
- einfacher ATR(14 Tage), anfänglicher Stop in vier ATR Abstand;
- kein festes Gewinnziel; ein nur enger werdender Vier-ATR-Stop folgt dem höchsten
  beziehungsweise niedrigsten abgeschlossenen Schlusskurs;
- Signal erst nach Kerzenschluss, Ausführung frühestens am nächsten Open;
- höchstens 1 % Kontorisiko je Einstieg und kleinster benötigter Hebel bis maximal
  10x.

Die Idee ist ein einfacher Test von Zeitreihen-Momentum über zwei Horizonte. Sie
folgt dem Grundprinzip aus Moskowitz, Ooi und Pedersen, ohne deren breit über viele
Märkte diversifiziertes Portfolio nachzubilden. Die Krypto-Studie von Han, Kang
und Ryu war ein zusätzlicher Anlass, Gebühren und realistische Ausführung von
Anfang an in das Tor einzubauen.

Quellen:

- [Moskowitz, Ooi und Pedersen: Time Series Momentum](https://fairmodel.econ.yale.edu/ec439/mosk.pdf)
- [Han, Kang und Ryu: Momentum in the Cryptocurrency Market](https://papers.ssrn.com/sol3/Delivery.cfm/4675565.pdf?abstractid=4675565&mirid=1)

## Kosten und Auswahlregel

Der normale Fall verwendet den bestandenen achtstündigen Kostenkandidaten:
0,05 % Taker-Gebühr je Ausführung, Spread-p95 von rund 0,119 Basispunkten,
nachteilige Slippage-p95 von rund 0,736 Basispunkten und konservatives Funding
von rund 0,001778 % je vier Stunden. Der Stressfall verdoppelt Gebühr, Spread,
Slippage und Funding. Die vollständige Herkunft steht im
[Kostenbericht](perpetual-cost-observation-2026-09-24.md).

Vor der ersten Ergebnisberechnung wurden Code, Datensätze, Kostenbelege und Regel
per SHA-256 eingefroren. Ein Bestehen hätte in jedem Jahr und beiden Kostenfällen
positiven Nettogewinn, weniger als 10 % Drawdown, mindestens drei Trades, keine
Liquidation und höchstens 10x Hebel verlangt. 2025 verletzt allein schon die
zentrale Positivitätsbedingung.

Protokoll-SHA-256:
`dfb93f1dbe7f2fb26fab25ca023b037e0e650fd127d161b22430b09b59bcd0ce`.
Ergebnis-SHA-256:
`e4eb34b1d5d897af6d3f13f3f096a6de988e090c557f558af9132f439ba42ac3`.

## Schlussfolgerung

Die große positive Spanne über 2023/2024 hätte ohne Jahrestor überzeugend wirken
können. Das negative Jahr 2025 zeigt, warum eine Gesamtaddition keine Freigabe
rechtfertigt. Auch verdoppelte Kosten sind nicht die Hauptursache: Schon der
beobachtete p95-Fall besitzt 2025 einen Profitfaktor unter eins. Weitere kleine
Änderungen an den beiden Horizonten oder am Stop würden dieselben gesehenen Daten
nachträglich optimieren. Für einen belastbaren nächsten Test braucht es eine neue,
strukturell begründete Regel und anschließend zeitlich neue Daten.

## Nachträgliche Richtungsdiagnose

Eine anschließend fest gebundene Diagnose zerlegte die unveränderten Trades nach
Richtung. 2024 erzielten LONG-Trades +115,92 USD, während SHORT-Trades
−47,18 USD verloren. Ein bloßes Abschalten von SHORT wäre trotzdem keine Lösung:
2025 verloren auch die tatsächlich entstandenen LONG-Trades −17,25 USD; die
SHORT-Trades verloren weitere −3,07 USD. Unter doppelten Kosten waren beide Seiten
ebenfalls negativ. Diese Zuordnung ist kein neuer LONG-only-Backtest, weil das
Entfernen einer Richtung spätere Einstiegsgelegenheiten verändern könnte.

Diagnose-SHA-256:
`31d9e60e5a5bb99ea30396f1a994292eeec31b1939af678f6155fb31d20f1a1c`.
Bericht-SHA-256:
`3315e3d08f9b92bbcb5a4e375b35a381db18eeea5de697ddece91fdc4e5034b1`.
