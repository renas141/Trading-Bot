# Derivate-Brokerprüfung, 24.09.2026

## Entscheidung

Kraken bleibt für die aktuelle PF_XBTUSD-Forschungsstrecke der passendste
technische Kandidat. Das ist keine Empfehlung zur Einzahlung und keine
Handelsfreigabe. Der Bot nutzt derzeit ausschließlich öffentliche Kraken-Daten;
eine private API- oder Orderanbindung existiert nicht.

Die Entscheidung beruht auf der Übereinstimmung zwischen Forschungsprodukt und
später möglichem Ausführungsprodukt: linearer BTC/USD-Perpetual, getrennte Trade-
und Mark-Preise, öffentlich dokumentierte Vierstundenkerzen, Funding- und
Orderbuchanalysen sowie ein API-Schema für Derivate. Der aktuelle Replay bildet
genau dieses Produkt konservativ nach.

## Aktuelle Kosten

Kraken nennt für Derivate in der ersten 30-Tage-Umsatzstufe 0,0200 % Maker und
0,0500 % Taker je Ausführung. Die Gebühr wird auf den Nominalwert berechnet.
Die im Replay verwendeten 0,0500 % Taker stimmen damit weiterhin überein.
[Offizielle Gebührentabelle](https://support.kraken.com/articles/360048917612-fee-schedule).

Funding ist bei linearen Perpetuals eine zusätzliche, fortlaufend berechnete
Zahlung und wird laut Kraken stündlich realisiert. Bei Multi-M-Collateral werden
Gebühren, P&L und Funding in USD geführt. Fehlt ausreichend USD, können
Umwandlungen und bei ungedeckten Verlusten weitere stündliche Belastungen
entstehen. Das lokale Modell nimmt keine solchen Umwandlungen an; eine spätere
Demo oder PAPER-Konfiguration muss daher mit ausreichend USD-naher Sicherheit
arbeiten oder diese Kosten ergänzen.

## EWR und Deutschland

Kraken verlangt von allen EWR-Kunden, die Derivate nutzen möchten, eine
MiFID-Einstufung, Steuerangaben und eine Eignungsprüfung. Ein Privatkunde muss
einen kurzen Produkttest absolvieren. Daraus folgt keine automatische
Berechtigung des konkreten Kontos; diese lässt sich erst im eingeloggten Konto
feststellen. [Kraken-Einstufung für EWR-Kunden](https://support.kraken.com/de/articles/how-does-classification-work).

Coinbase hat im März 2026 in Deutschland und weiteren europäischen Ländern
regulierte Futures schrittweise eingeführt. Die Produktbeschreibung nennt dabei
unter anderem „perpetual-style“ Kontrakte mit fünf Jahren Laufzeit. Das ist nicht
dasselbe Instrument wie Krakens unbegrenzt laufender PF_XBTUSD-Perpetual. Für
einen belastbaren Coinbase-Vergleich wären deshalb ein eigener Kontraktadapter,
eigene historische Kurse, Settlement-Regeln, Gebühren und gemessene Spreads
nötig. [Coinbase-Mitteilung für Europa](https://www.coinbase.com/blog/futures-contracts-europe).

## Demo-Umgebung

Krakens Supportseite vom 7. Juli 2026 ist widersprüchlich: Sie kündigt die
Abschaltung der bisherigen `demo-futures.kraken.com`-Umgebung zum 14. Juli an,
beschreibt danach aber weiterhin denselben Host als Testumgebung. Beim aktuellen
öffentlichen Abruf leitete der dort genannte Ticker-Endpunkt auf eine
Produktseite um. Der Bot darf diesen Host daher nicht als verlässlich verfügbare
Demo voraussetzen. Vor einer Demo-Integration muss Kraken den aktuellen Endpunkt
bestätigen und ein neuer, getrennt erzeugter Demo-Schlüssel ausschließlich in der
Testumgebung geprüft werden. [Kraken API Testing Environment](https://support.kraken.com/articles/360024809011-api-testing-environment-derivatives).

## Freigabereihenfolge

1. Eine Strategie muss zuerst ein vorab festgelegtes Entwicklungstor und danach
   einen einzigen unabhängigen Holdout bestehen. Das ist bisher nicht geschehen.
2. Danach folgt ein dauerhafter lokaler PAPER-Lauf mit öffentlichen Quotes,
   simulierten Fills, Wiederaufnahme und Kostenbeobachtung über mehrere
   Marktphasen.
3. Erst anschließend darf eine bestätigte Kraken-Demo-Umgebung mit getrennten
   Demo-Zugangsdaten angebunden werden.
4. Eine Produktionsanbindung bleibt ein eigener späterer Schritt. Dazu gehören
   Kontoberechtigung, tatsächlich angezeigter Marginplan, Collateral,
   Mindestgröße, API-Rechte, Kill Switch und ein manueller Abbruchtest.

Hebel bis 10x bleibt eine technische Obergrenze. Die Positionsgröße entsteht aus
dem Stop-Risiko; der Risk Manager wählt den kleinsten dafür benötigten Hebel. In
den neuen Studien wurden trotz erlaubter 10x höchstens 3x verwendet. Das ist die
gewünschte Wirkung: mehr erlaubter Hebel vergrößert nicht automatisch die
Position.
