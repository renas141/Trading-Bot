# Bot-Reifebericht

Der Reifebericht fasst die entscheidenden Einsatzsperren an einer Stelle zusammen.
Er bewertet keine Strategie neu und kann weder PAPER noch LIVE freischalten. Jede
widersprüchliche oder unvollständige Quelle führt zu einem Fehler statt zu einer
positiven Anzeige.

## Bericht erzeugen

```bash
.venv/bin/python -m app.readiness --output data/readiness/status.json
```

Geprüft werden:

- Unverändertheit des vorab festgelegten Forward-Protokolls und seiner
  Kostenannahmen;
- Prüfsummen, zeitliche Lücken und Stand sämtlicher PF_XBTUSD-Forward-Pakete;
- gültige Abschlussbelege für Screen und Holdout;
- aktueller öffentliche Vertragsnachweis einschließlich der EWR-Obergrenze von
  10x;
- gesperrter PAPER-Status;
- ein optionaler, entschärfter Nachweis des persönlichen Kraken-Lesezugangs.

Das Dashboard liest anschließend ausschließlich
`data/readiness/status.json`. Der Bericht enthält keine Zugangsdaten und bleibt
zusammen mit den übrigen Laufzeitdaten von Git ausgeschlossen.

## Persönlichen Kraken-Zugang nachweisen

Voraussetzung ist ein eigener API-Schlüssel mit **General READ_ONLY** und
**Transfer NO_ACCESS**. Schlüssel und Secret werden nur über die lokalen
Prozessvariablen `KRAKEN_FUTURES_API_KEY` und
`KRAKEN_FUTURES_API_SECRET` eingelesen. Sie dürfen nicht in Git, eine Datei im
Projekt oder einen Chat kopiert werden.

Nach dem lokalen Setzen der beiden Variablen:

```bash
.venv/bin/python -m app.exchange.kraken_futures_readonly verify \
  --output data/evidence/kraken-readonly/account-summary.json
.venv/bin/python -m app.readiness --output data/readiness/status.json
```

Vor allen anderen Abfragen prüft der Client die Schlüsselrechte. Ein
überberechtigter Schlüssel wird sofort abgelehnt. Der gespeicherte Nachweis enthält
nur Rechte, Zähler, Zugänglichkeit und Berechtigung für PF_XBTUSD sowie die
persönliche Mindestmenge. Rohantworten, Kontosalden, Positionen, Fills, Schlüssel
und Secret werden nicht gespeichert.

## Aktueller Stand am 06.10.2026

- 69 lückenlose Pakete bis 20:00 UTC, davon 55 vorab ausgeschlossen;
- 14 von 180 neuen Screen-Blöcken, entsprechend 7,78 Prozent;
- Screen frühestens nach dem Block bis 02.11.2026, 12:00 UTC auswertbar;
- der 360-Blöcke-Holdout darf nur nach bestandenem Screen geöffnet werden;
- öffentlicher PF_XBTUSD-Vertrag und 10x-Obergrenze bestätigt;
- persönlicher Lesezugang noch nicht bestätigt;
- Profitabilität nicht nachgewiesen, kein PAPER-Kandidat, LIVE gesperrt.

Für zusätzliche Entwicklung wurden 1.599 lückenlose PF_XBTUSD-Trade- und
Mark-Kerzen aus 2026 geladen. Die getrennte Diagnose war in beiden Kostenfällen
positiv, wird aber als gesehene Entwicklungsperiode behandelt und zählt nicht als
Forward-Nachweis. Vor einem späteren PAPER-Einstieg prüft ein zusätzlicher Gate
Quote-Alter, Spread, Kursabweichung und das Verhältnis der erwarteten
Ausführungskosten zum Stop-Abstand.

Zusätzlich zeigt der Bericht den getrennten
[adaptiven Paralleltest](adaptive-leverage-safety-2026-10-05.md). Dessen Regeln
und Auswerter wurden vor dem Start am 05.10.2026, 20:00 UTC gebunden. Seine
Blöcke, Risikostufen und Ergebnisse werden nicht mit dem ersten Kandidaten
vermischt.

Ein bestandener Holdout wäre ein Ergebnis auf zeitlich späteren Daten und nur die
Voraussetzung für einen längeren Shadow-PAPER-Lauf. Er garantiert keine künftigen
Gewinne.
