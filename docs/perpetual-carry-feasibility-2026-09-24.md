# Vorprüfung: marktneutraler Spot/Perpetual-Carry

Stand: 24.09.2026. Ergebnis: **noch nicht forschungsreif und nicht zur
Ausführung freigegeben.**

Die strukturelle Idee wäre, BTC am Spotmarkt zu kaufen und denselben Nominalwert
im Perpetual short zu halten. Bei positivem Funding zahlt die Long-Seite an die
Short-Seite; die entgegengesetzten Kurspositionen sollen einen großen Teil des
BTC-Richtungsrisikos neutralisieren.

## Gebührenhürde

Kraken veröffentlicht für die Einstiegsstufe derzeit 0,40 % Spot-Maker und
0,80 % Spot-Taker sowie 0,02 % Futures-Maker und 0,05 % Futures-Taker. Für das
Öffnen und spätere Schließen beider Legs ergibt das vor Spread und Slippage:

| Annahme | Spot hin/zurück | Perpetual hin/zurück | Gesamthürde |
| --- | ---: | ---: | ---: |
| beide Legs Maker | 0,80 % | 0,04 % | **0,84 %** |
| beide Legs Taker | 1,60 % | 0,10 % | **1,70 %** |

Quelle: [Kraken Fee Schedule](https://www.kraken.com/features/fee-schedule),
abgerufen am 24.09.2026. Maker-Ausführung ist nicht garantiert; ein nicht sofort
ausgeführter Hedge erzeugt zusätzliches Kursrisiko.

Der erste verifizierte Funding-Tag summierte sich auf rund 0,01693 % zugunsten
eines Short-Perpetuals. Bei unverändertem Funding wären allein zur Deckung der
Gebühren grob 50 Tage im Maker-Fall beziehungsweise 100 Tage im Taker-Fall
nötig. Diese Rechnung ignoriert Spread, Slippage, Basisänderung, Steuern,
Kapitalbindung, mögliche negative Funding-Phasen und Liquidationspuffer.

## Daten- und Betriebsgrenzen

Die öffentliche `future-basis`-Probe war technisch verfügbar, lieferte an dem
geprüften Tag aber nur grob gerundete Werte von überwiegend `0.0000` und
vereinzelt `0.0001`. Das reicht nicht für eine belastbare Basisrisiko- und
Ausführungsrechnung. Historisches Funding für 2023–2025 war über den geprüften
Analytics-Endpunkt nicht verfügbar.

Ein Carry-Modell braucht außerdem zwei atomar koordinierte Legs, getrennte
Spot-/Perpetual-Orderbücher, Teilfüllungsbehandlung, ausreichend zusätzliches
Collateral und eine Notfallregel, falls nur eine Seite ausgeführt wird. Diese
Mechanik ist im aktuellen Bot nicht implementiert.

Der Ansatz wird deshalb nicht backgetestet und nicht als weitere Strategie
gezählt. Sinnvoll wäre erst eine längere gemeinsame Forward-Reihe aus Funding,
Spot-/Perpetual-Bid/Ask und Basis. Bis dahin bleibt der erwartete Ertrag gegenüber
der Gebühren- und Betriebsunsicherheit zu schwach belegt.
