# PF_XBTUSD-Regimedaten

Stand: 24.09.2026. Diese Daten erweitern die Forschung, aktivieren aber weder
eine Strategie noch PAPER oder LIVE.

## Quelle und Felder

Die öffentliche Kraken-Futures-Analytics-API liefert Zeitreihen in wählbaren
Intervallen. Verwendet werden ausschließlich `PF_XBTUSD`, vier Stunden und die
sechs Typen Open Interest, Aggressor-Differenz, Liquidationsvolumen, rollende
Volatilität, Long/Short-Verhältnis und CVD. Aus CVD werden zusätzlich Kauf- und
Verkaufsvolumen gespeichert. Die offizielle Beschreibung steht im
[Kraken API Center](https://docs.kraken.com/api/docs/futures-api/charts/market-analytics).

Jede Rohantwort bleibt lokal erhalten und ist im Manifest mit URL und SHA-256
gebunden. Der Lader prüft Dateien, Zeitachse, Schema, Zahlenbereiche und
Abdeckung erneut. Downloads erlauben nur den fest eingebauten HTTPS-Host,
`PF_XBTUSD`, die sechs bekannten Typen, vier Stunden und höchstens 370 Tage.
Weiterleitungen, übergroße Antworten und unvollständige Seiten werden
abgelehnt.

## Verifizierte lokale Pakete

| Paket | Gemeinsame Abdeckung (UTC, Ende exklusiv) | Zeilen | Rohseiten | Manifest SHA-256 | CSV SHA-256 |
| --- | --- | ---: | ---: | --- | --- |
| 2023 | 31.05.2023 12:00 bis 01.01.2024 00:00 | 1.287 | 12 | `2b02978a4430a93e53739a491c75ffacf4a8da226f2fca63e56651226a9f948f` | `c0d6a68fe7a37870b2ea871f6db66eaa8b79f7f02e0c7c8666442898e1e72394` |
| 2024 | 01.01.2024 00:00 bis 01.01.2025 00:00 | 2.196 | 12 | `6e03ab7a9f2c46a455affee5d2de4b1ed22c69d6f2a58239d83bfe55391c72a2` | `46322c773bb10378e51baec522f38b0a46e2fb5b3e5e99960597cf20c47b1b96` |
| 2025 | 01.01.2025 00:00 bis 01.01.2026 00:00 | 2.190 | 12 | `eb7ea672eeb8c7aa0d52e7af82ee9e2ad9695d173eaf570f79dc6fba073dc9d6` | `aaa375684d25a8945cf9b6f40e2ead6f62820bb5698f5ce8e71cee654d2cb589` |

Alle sechs Reihen sind innerhalb ihrer gemeinsamen Abdeckung lückenlos. Die
verkürzte 2023-Abdeckung entsteht durch den späteren Beginn einzelner
Analytics-Reihen und wird nicht aufgefüllt.

Ein separater technischer Ein-Punkt-Test vom 24.09.2026 speicherte alle sechs
Rohantworten erfolgreich. Er prüft nur den aktuellen Datenweg und sagt nichts
über Vorhersagekraft oder typische Marktphasen aus.

## Zeitliche Verknüpfung

Kurskerzen tragen ihren Öffnungszeitpunkt. Für die Forschung wird ein
Analytics-Bucket mit Zeitstempel `t` zunächst als erst nach `t + 4h`
abgeschlossen behandelt. Er darf erst zur nächsten Kurskerze gehören; deren
Signal entsteht bei `t + 8h`. Dieser zusätzliche volle Vierstundenabstand ist
absichtlich konservativ, weil die öffentliche Dokumentation keinen belastbaren
Veröffentlichungszeitpunkt je Bucket nennt.

Die verifizierte Überschneidung umfasst 1.286 Kurskerzen ab 31.05.2023 16:00,
2.195 Kurskerzen in 2024 und 2.189 Kurskerzen in 2025. Die Verknüpfung lehnt
Lücken, doppelte Zeitstempel, abweichende Trade-/Mark-Zeitachsen und ungeprüfte
Zahlen ab.

## Forschungsgrenzen

Die Kursresultate 2023–2025 sind Entwicklungsdaten. In einer begrenzten
Exploration wurden acht sachlich begründete Kombinationen aus 7-/28-Tage-Trend,
steigendem Open Interest, Aggressor-/CVD-Fluss und Long/Short-Crowding angesehen.
Das ist Mehrfachprüfung und kein unabhängiger Beleg.

Für 2026 wurden Regimewerte technisch geladen und einzelne Werte angesehen,
aber keine PF_XBTUSD-Kursperformance geladen oder berechnet. Eine spätere
2026-Auswertung wäre damit ergebnisblind, aber wegen der bereits gesehenen
Merkmalsverteilung nicht vollständig blind. Ein streng unabhängiger Zeitraum
für eine daraus abgeleitete Regel beginnt erst nach dem 24.09.2026.

Regimedaten können Fehlentscheidungen verringern, garantieren aber keine
Profitabilität. Vor einer Auswertung wird genau eine Regel samt Kosten, Stop,
Haltedauer und Auswahlgrenze eingefroren. Änderungen nach Sichtung des
Ergebnisses zählen als neue Hypothese.
