# Öffentliche Bitvavo-Daten

Der Adapter liest ausschließlich BTC/EUR-Kerzen, aktuelle Instrumentregeln und
Geld-/Briefkurse. Er benötigt keinen API-Schlüssel und besitzt keine Orderfunktion.
Herkunft und Originalantworten bleiben mit Prüfsummen erhalten.

Die [offizielle Kerzen-Schnittstelle](https://docs.bitvavo.com/docs/rest-api/get-candlestick-data/)
liefert neueste Kerzen zuerst und lässt Intervalle ohne Trades aus. Der Adapter
prüft die Reihenfolge vor dem Umkehren; doppelte oder außerhalb des angeforderten
Zeitraums liegende Kerzen werden abgelehnt. Pro Anfrage höchstens 1.440 Kerzen,
pro Import höchstens 16 Seiten. Lücken werden nicht ergänzt.

Ein echter Probeabruf für 01.01.2023 bestätigte die Endgrenze: Bei 00:00–08:00 UTC
werden die beiden 4h-Kerzen 00:00 und 04:00 geliefert. Ein um 1 ms verkürztes Ende
entfernt die letzte Kerze. Der Import verwendet deshalb ausgerichtete Grenzen und
speichert kanonisch das halboffene Intervall [Start, Ende).

```sh
.venv/bin/python -m app.market_data.bitvavo history \
  --start 2023-01-01T00:00:00Z --end 2025-01-01T00:00:00Z \
  --timeframe 4h --output data/datasets/bitvavo_btc_eur_4h_2023_2024
.venv/bin/python -m app.market_data.bitvavo snapshot \
  --output data/evidence/bitvavo_snapshot_20260923
```

Beide Zielordner existieren bereits aus der Nachtarbeit. Für neue Abfragen einen
neuen Namen verwenden. Der historische Import enthält 4.386 von 4.386 erwarteten
Kerzen, ohne Lücken. 2025 wurde nicht als Strategiezeitraum ausgewertet.

Die Instrumentregeln stammen aus einer aktuellen öffentlichen Abfrage: unter
anderem 1 EUR Preisschritt und getrennte Mindestmengen in BTC und EUR. Sie sind
kein Beleg historischer Handelsregeln. Der zusätzliche Quote-Snapshot besitzt
keinen Börsen-Ereigniszeitstempel; gespeichert werden lokale Anfrage-/Empfangszeit.
Ein einzelner Geld-/Briefkurs belegt weder typische Spreads noch die für unsere
Ordergröße verfügbare Markttiefe. Gebührenvergleich: [Brokerkosten](broker-costs.md).
