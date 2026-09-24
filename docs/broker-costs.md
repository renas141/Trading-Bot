# Broker- und Gebührenvergleich

Recherche vom 23.09.2026. Vergleich für vollständig finanzierten BTC/EUR-Spot-Handel,
kleines Anfangskonto, ohne Abo, Rabatt-Token oder bereits erreichte Umsatzstufen.
Die konkrete Kontoeinstufung wurde nicht eingesehen. Ausführungsgüte und Spreads
sind hier noch nicht empirisch über mehrere Tage verglichen.

| Anbieter / Produkt | Maker je Seite | Taker je Seite | Grobe Taker-Gebühr für Kauf und Verkauf mit je 1.000 EUR Gegenwert |
| --- | ---: | ---: | ---: |
| Kraken Pro, Einstiegstarif | 0,40 % | 0,80 % | 16 EUR |
| Coinbase Advanced, EU/UK-Einstiegstarif | 0,25 % | 0,50 % | 10 EUR |
| Bitvavo, EUR-Märkte, erste Stufe | 0,15 % | 0,25 % | 5 EUR |

Kraken nennt seit der Umstellung im Juli 2026 höhere Einstiegstarife und abgestufte
Ermäßigungen. Die bisherige Forschungsannahme von 0,26 % ist **kein aktueller
Kraken-Einstiegstarif**. Quellen: [Gebührentabelle](https://www.kraken.com/features/fee-schedule),
[Änderung der Stufen](https://support.kraken.com/articles/cross-platform-fee-tier-changes).

Coinbase nennt seit 16.09.2026 ausdrücklich regionale Tarife; für EU/UK gelten
die oben genannten Einstiegssätze. Ältere Hilfeseiten mit pauschalen 0,4/0,6 %
wurden deshalb nicht als aktueller Maßstab verwendet. Quellen:
[Ankündigung](https://www.coinbase.com/blog/were-lowering-fees-for-many-active-traders-on-coinbase-advanced),
[Kontobezogene Gebühren](https://help.coinbase.com/en/coinbase/trading-and-funding/advanced-trade/advanced-trade-fees).

Bitvavo veröffentlicht für EUR-Paare in der ersten Volumenstufe 0,15/0,25 %.
Die ausgewiesenen USDC-Tarife sind nicht direkt mit BTC/EUR gleichzusetzen:
Umtauschkosten, zusätzliches Preisrisiko und ein anderes Orderbuch wären einzurechnen.
Quelle: [Bitvavo-Gebühren](https://bitvavo.com/en/fees).

Die Zahlen in der letzten Spalte sind ein einfacher Vergleich bei gleichem
Kauf- und Verkaufsgegenwert. Tatsächliche Gebühren hängen von der Positionsgröße
und dem Ausstiegskurs ab. Spread und Slippage kommen hinzu. Ohne diese Kosten
liegt die notwendige Kursbewegung zum Ausgleich gleicher Kauf-/Verkaufsgebühren
bei `(1 + f) / (1 - f) - 1`, also etwas über `2 × f`.

## Entscheidung für die Entwicklung

Bitvavo ist unter diesen drei geprüften EUR-Einstiegstarifen der günstigste
Kandidat für einen zusätzlichen öffentlichen Datenadapter und späteren
Paper-Vergleich. Das ist noch keine endgültige Empfehlung, dort Geld einzuzahlen.
Zuerst fehlen ein vergleichbarer Datensatz, gemessene Spreads und Prüfung der
konkreten Konto-/Produktverfügbarkeit. Die veröffentlichte MiCAR-Mitteilung ist
ein Ausgangspunkt, kein Nachweis individueller Berechtigung:
[Bitvavo-Lizenzmitteilung](https://bitvavo.com/en/news/bitvavo-obtains-mica-licence).

Kraken bleibt die Quelle unserer bisherigen Historie. Niedrigere Fremdbroker-
Gebühren auf Kraken-Kerzen wären nur eine Sensitivitätsrechnung, kein Backtest
des anderen Brokers. Eine Migration darf nicht durch Austausch einer Gebührenzahl
vorgetäuscht werden.

Maker-Gebühren setzen tatsächliche passive Ausführungen voraus. Ein Limit allein
garantiert weder Maker-Status noch Ausführung. Für einen Stop oder sofortigen
Ausbruchseinstieg bleibt ein Taker-Modell die konservative Arbeitsgrundlage.
Rabattstufen dürfen erst nach modelliertem, tatsächlich erreichtem Umsatz gelten;
das aktuelle Experiment hält die Einstiegskosten konstant und behauptet keine
historisch exakte Gebührenrekonstruktion.

## Getrennte Derivate-Entscheidung

Funding, Margin, Liquidationen und ein lineares Perpetual-Risikomodell sind
inzwischen im lokalen Replay umgesetzt. Kraken bleibt für `PF_XBTUSD` der
technisch passende Forschungskandidat; der Einstiegstarif liegt aktuell bei
0,0200 % Maker und 0,0500 % Taker. EWR-Kunden müssen ihre MiFID-Eignung und das
konkrete Produkt im Konto bestätigen. Die aktuelle Demo-Dokumentation ist
widersprüchlich und der frühere Demo-Endpunkt leitete bei der Prüfung um. Details,
Quellen und die festgelegte Freigabereihenfolge stehen in der
[Derivate-Brokerprüfung vom 24.09.2026](derivative-broker-review-2026-09-24.md).

Niedrige Handelsgebühren machen eine negative Strategie nicht profitabel. Funding,
Spread, Slippage, Collateral-Umwandlungen und Kurslücken bleiben zusätzlich zu
modellieren beziehungsweise im PAPER-Betrieb zu messen.
