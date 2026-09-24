# Kurzfristiges Zeitreihen-Momentum, 24.09.2026

## Ergebnis

Der genau einmal geprüfte kurzfristige Momentum-Kandidat bestand das
Entwicklungstor nicht. 2023 und 2024 waren beide Kostenfälle positiv; 2025 war
beide Male negativ. Es gibt keine Auswahl und keine PAPER- oder LIVE-Freigabe.
PF_XBTUSD-Kursdaten ab 2026 wurden nicht geladen oder ausgewertet.

| Jahr | Kostenfall | Trades | Netto USD | Profitfaktor | Max. Drawdown | Max. Hebel |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2023 | beobachtetes p95 | 52 | +146,44 | 1,680 | 6,70 % | 3x |
| 2023 | doppelte Kosten | 52 | +113,96 | 1,523 | 6,88 % | 2x |
| 2024 | beobachtetes p95 | 61 | +120,10 | 1,432 | 7,63 % | 2x |
| 2024 | doppelte Kosten | 61 | +92,33 | 1,330 | 7,93 % | 2x |
| 2025 | beobachtetes p95 | 65 | −38,90 | 0,886 | 9,09 % | 2x |
| 2025 | doppelte Kosten | 65 | −71,12 | 0,791 | 9,61 % | 2x |

## Vorab festgelegte Regel

Die Regel wurde aus dem in der Forschung berichteten Krypto-Momentum über ungefähr
eine bis acht Wochen abgeleitet. Sie nutzt genau eine Konfiguration:

- LONG bei gemeinsam positiver 7- und 28-Tage-Rendite;
- SHORT bei gemeinsam negativer 7- und 28-Tage-Rendite;
- sonst HOLD;
- ATR über sieben Tage und anfänglicher Stop im Abstand von drei ATR;
- kein Gewinnziel und kein nachgezogener Stop;
- Schließung nach spätestens sieben Tagen, entschieden am Schlusskurs und
  ausgeführt am nächsten Open;
- maximal 1 % Kontorisiko und kleinster benötigter Hebel bis 10x;
- derselbe beobachtete p95-Kostenfall wie in der vorherigen Studie sowie ein Fall,
  der Gebühr, Spread, Slippage und Funding verdoppelt.

Quelle: [Liu und Tsyvinski, Risks and Returns of Cryptocurrency](https://www.nber.org/papers/w24877).

## Tor und Integrität

Jedes Jahr und jeder Kostenfall musste Nettogewinn, weniger als 10 % Drawdown,
mindestens zwölf Trades, keine Liquidation und höchstens 10x Hebel erreichen.
Parameter, Code, Daten und Kostenbelege wurden vor der ersten Ergebnisberechnung
per SHA-256 eingefroren. Es gab keine Ersatzvariante und keine nachträgliche
Parameteränderung.

Protokoll-SHA-256:
`745f2f1995f0b274fbf20dd9adf11437ed98c43b7df6765d15b098ea3317e833`.
Ergebnis-SHA-256:
`71bf72ecdda76a2e4c7c6c8fda92d4cd39c5b883806915698c448771642db736`.

## Befund

Der kürzere Horizont erhöhte die Zahl der Trades deutlich, veränderte aber das
Jahresmuster nicht: zwei positive Entwicklungsjahre und ein negatives Jahr 2025.
Die Verluste steigen unter doppelten Kosten, doch schon der beobachtete Fall hat
2025 einen Profitfaktor unter eins. Weitere Varianten der Momentum-Horizonte auf
denselben Daten würden die Mehrfachtest- und Überanpassungsgefahr erhöhen. Diese
Momentum-Forschungsfolge ist deshalb beendet.
