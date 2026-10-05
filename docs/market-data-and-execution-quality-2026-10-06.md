# Marktdaten und Ausführungsqualität, 06.10.2026

## Neue Datenbasis

Der neue öffentliche PF_XBTUSD-Historienabruf akzeptiert nur Kraken Futures,
Trade- und Mark-Kerzen, vier Stunden sowie einen ausgerichteten Zeitraum von
höchstens 370 Tagen. Jede Seite wird roh gespeichert, die Pagination muss
vorwärts fortschreiten und Trade- und Mark-Zeitachsen müssen vollständig
übereinstimmen.

Für den Zeitraum 01.01.2026 bis 24.09.2026, 12:00 UTC wurden jeweils 1.599
Trade- und Mark-Kerzen ohne Lücke geladen. Zusammen mit 2023–2025 liegen damit
8.175 geprüfte Vierstundenblöcke vor. Die 2026-Periode ist ab jetzt gesehene
Entwicklungsinformation. Sie darf die bereits laufenden Zukunftstests weder
ersetzen noch nachträglich verändern.

Der Versuch, lückenlose stündliche Funding-Daten ab Januar 2026 abzurufen,
scheiterte an fehlenden Stunden in der öffentlichen Kraken-Reihe. Es wurden
keine Werte ergänzt. Die Diagnose verwendet deshalb dieselbe vorab festgelegte
adverse Funding-Sensitivität wie die ältere Entwicklungsstudie.

## 2026-Diagnose

Die unveränderte regimebestätigte Momentumregel wurde auf den neu geöffneten
2026-Daten mit einem frischen virtuellen Konto von 1.000 USD geprüft:

| Kostenfall | Trades | Netto | Profitfaktor | Max. Drawdown | Max. Hebel |
| --- | ---: | ---: | ---: | ---: | ---: |
| beobachtetes p95 | 18 | +111,83 USD | 2,54 | 4,53 % | 2x |
| doppelte Kosten | 18 | +98,35 USD | 2,32 | 4,79 % | 2x |

Es gab keine Liquidation. Diese Auswertung ist positiv, aber rückblickend. Sie
beweist keine künftige Profitabilität. LONG und SHORT blieben aktiv, weil die
Richtungsergebnisse zwischen 2023, 2024, 2025 und 2026 wechselten und keine
stabile Grundlage zum Abschalten einer Richtung ergaben.

## Neue Ausführungsprüfung

Vor einem späteren PAPER-Einstieg kann der Bot jetzt einen aktuellen Bid-/Ask-
Quote prüfen. Ein Einstieg wird abgelehnt, wenn:

- der Quote älter als 20 Sekunden oder aus der Zukunft ist;
- der Spread über fünf Basispunkten liegt;
- der Mittelpunkt mehr als zehn Basispunkte vom geplanten Einstieg abweicht;
- geschätzte Gebühren, Spread und Slippage zusammen mehr als 25 Prozent des
  geplanten Stop-Abstands verbrauchen.

Die Prüfung berechnet für LONG und SHORT jeweils einen nachteiligen Einstiegs-
und Stop-Fill. Sie ist fail-closed: Fehlen belastbare aktuelle Ausführungsdaten,
darf kein späterer Orderpfad daraus eine Freigabe ableiten. PAPER und LIVE
bleiben bis zum bestandenen Zukunftstest ausgeschaltet.
