# Derivate-Brokerentscheidung, 04.10.2026

## Ergebnis

Kraken bleibt der technische Zielbroker für die bestehende
`PF_XBTUSD`-Forschungsstrecke. Diese Festlegung spart keinen Prüfpunkt aus und
ist keine Freigabe für Einzahlung oder Handel. Sie verhindert zunächst einen
unnötigen Wechsel des Instruments: Daten, Funding, Markpreis, Kostenmessung,
Replay und PAPER-Beobachter beziehen sich bereits konsistent auf denselben
linearen Bitcoin/USD-Perpetual.

Die Entscheidung gilt nur unter zwei noch offenen persönlichen Voraussetzungen:

1. Das konkrete EWR-Konto muss den Derivatezugang nach der MiFID-Einstufung
   tatsächlich anzeigen.
2. Ein getrennt angelegter API-Schlüssel muss exakt `READ_ONLY` für allgemeine
   Daten und `NO_ACCESS` für Transfers besitzen.

Für alle EWR-Kunden verlangt Kraken vor dem Derivatezugang Steuerangaben und eine
Einstufung als Privat- oder professioneller Kunde. Privatkunden müssen einen
Produkttest absolvieren. Das belegt den Prozess, aber noch nicht die Freigabe
dieses Kontos. Quelle: [Kraken zur EWR-Einstufung](https://support.kraken.com/articles/how-does-classification-work),
aktualisiert am 19.08.2026.

## Kosten und Produktpassung

Für die erste Derivate-Umsatzstufe nennt Kraken unverändert `0,0200 %` Maker und
`0,0500 %` Taker je Ausführung, jeweils auf den Nominalwert. Der aktuelle Replay
verwendet konservativ die Taker-Gebühr. Quelle:
[Kraken Derivategebühren](https://support.kraken.com/articles/360048917612-fee-schedule),
aktualisiert am 05.09.2026.

Ein Kauf und späterer Verkauf mit jeweils 1.000 USD Nominalwert kostet in dieser
Stufe zusammen 1 USD reine Taker-Gebühr. Spread, Slippage und Funding kommen
hinzu. Der niedrige Satz macht eine Strategie nicht profitabel; er verringert
nur eine bekannte Kostenkomponente.

Coinbases europäische Futures bleiben ein späterer Vergleichskandidat. Das dort
beschriebene europäische Produkt besitzt jedoch eine andere Laufzeit- und
Settlement-Struktur. Ein Wechsel wäre daher eine neue Studie mit eigenen Daten,
Kosten und Ausführungsregeln und kein Austausch einer Gebührenzahl im bestehenden
Kraken-Replay.

## Umgesetzte Kontoprüfung

Der neue [nur-lesende Kraken-Client](kraken-futures-readonly.md) bildet den
nächsten kontrollierbaren Schritt ab. Kraken dokumentiert, dass Wallets und
offene Positionen mindestens allgemeine Leserechte benötigen. Der separate
[API-Schlüsselprüfpunkt](https://docs.kraken.com/api-reference/api-keys/check-v3-api-key)
meldet `NO_ACCESS`, `READ_ONLY` oder `FULL_ACCESS` für allgemeine und
Transferrechte. Der Bot akzeptiert davon nur die engste Kombination
`READ_ONLY`/`NO_ACCESS`.

## Freigabestatus

| Prüfung | Stand |
| --- | --- |
| Instrument passt zu Daten und Replay | erfüllt |
| Aktuelle Einstiegskosten im Modell | erfüllt |
| Rein lesende Kontoschnittstelle | fertig und getestet |
| Persönlicher EWR-Derivatezugang | ohne Konto noch offen |
| Persönlicher Marginplan und Collateral | ohne Konto noch offen |
| Aktuelle Demo-Umgebung | alter Host abgeschaltet; kein Demo-Client möglich |
| Unabhängiger Forward-Screen | noch nicht genügend Daten |
| Unabhängiger Holdout | noch nicht begonnen |
| Echte Orderanbindung | nicht vorhanden und gesperrt |

Die Reihenfolge bleibt daher: Forward-Daten sammeln, Screen und Holdout bestehen,
lang laufendes PAPER prüfen, persönliche Leseberechtigung verifizieren und erst
danach eine bestätigte Demo-Umgebung untersuchen. LIVE bleibt gesperrt.

## Ergänzung: Vertrag und Demo-Umgebung

Der erneute [öffentliche Vertragsabruf vom 04.10.2026](kraken-pf-xbtusd-contract-2026-10-04.md)
bestätigt Preisschritt, Mengenpräzision und die 10x/10 %/5 %-Annahmen des lokalen
EWR-Retail-Modells. Die konkrete Mindestordergröße wird öffentlich nicht geliefert
und bleibt deshalb Teil der späteren persönlichen Lesekontrolle.

Die frühere Demo-Umgebung kann nicht weiterverwendet werden. Krakens eigene, am
07.07.2026 aktualisierte [Demo-Seite](https://support.kraken.com/articles/360024809011-api-testing-environment-derivatives)
nennt die Abschaltung zum 14.07.2026, enthält daneben aber noch die alte Anleitung.
Beim erneuten Direktabruf am 04.10.2026 leitete selbst der dokumentierte
`/derivatives/api/v3/tickers`-Endpunkt auf die normale Kraken-Produktseite um.
Damit wird kein Demo-Client gegen diesen Host gebaut. Nach bestandenem Forward-
Holdout muss Kraken eine neue offizielle Testumgebung nennen; andernfalls bleibt
die nächste Stufe ein länger laufender lokaler PAPER-Betrieb.
