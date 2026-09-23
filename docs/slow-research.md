# Dritte Hypothese: BTC/EUR auf vier Stunden

Die bisherigen 15-Minuten-Ergebnisse liefern keinen ausreichenden Handelsvorteil.
Der neue Versuch prüft, ob die unveränderten Ausbruchsregeln auf 4-Stunden-Kerzen
ausreichend Kursbewegung nach Kosten übrig lassen. Das ist eine Hypothese, keine
Erwartung garantierter Gewinne. Es findet keine Parametersuche statt.

Primärer Kandidat: `trend_breakout` 0.1.0 plus Nettoziel-Risiko-Verhältnis ≥ 1 am
tatsächlichen nächsten Einstiegskurs. Die ungefilterte Regel ist ein beschreibender
Vergleich. Sie kann bei Scheitern des Kandidaten nicht zum Sieger erklärt werden.
Alle bisherigen Bar-Anzahlen, ATR-Multiplikatoren und Risikogrenzen bleiben gleich.

2023/2024 müssen einzeln bei normalen und doppelten Kosten positiv abschneiden,
je mindestens 20 Trades ausführen und unter 10 % beobachtetem Drawdown bleiben.
Nur dann darf 2025 mit exakt denselben Regeln ausgewertet werden. Die Mindestzahl
ist eine Konvention, kein Signifikanztest. Jedes Jahr beginnt mit eigenem Konto
und 50 Aufwärmkerzen. Cash und Kaufen-und-Halten sind separate Referenzen.

## Aktueller Stand

**Ursprünglicher Plan vor Performance-Berechnung gesperrt:** Im offiziellen 4h-Archiv fehlen
14.04.2024, 04:00–08:00 UTC und 01.11.2025, 16:00–20:00 UTC. Auch im Stundenarchiv
fehlen die entsprechenden Kerzen. Keine synthetischen Kurse, keine nachträgliche
Auswahl kürzerer Abschnitte. 2025 bleibt hinsichtlich Strategieergebnissen ungesehen.

Nachtrag 23.09.2026: Die [Einzeltrade-Prüfung](data-reconciliation.md) bestätigt
leere veröffentlichte Handelsintervalle. Ein separates, vor Berechnung eingefrorenes
Pausenmodell erlaubt deshalb eine nachvollziehbare Auswertung ohne künstliche Kerzen.
`data/research/slow_4h_observed_v3` enthält 16 Läufe mit vier Kostenfällen. Die
Prüfung auf 2023/2024 ist nicht bestanden; 2025 bleibt zurückgehalten.

Bericht: `data/research/slow_4h_2023_2025_v2/report.md`.
Die Daten und Berichte sind wie bisher lokal und werden nicht in Git aufgenommen.

## Werkzeuge

Der neue Downloader lädt nur eine ausgewählte BTC/EUR-Datei aus fünf zusammengehörigen
offiziellen ZIP-Teilen. Er begrenzt den Gesamttransfer auf 20 MB und die entpackte
Datei auf 100 MB; unterstützt werden 1h und 4h. Lücken bleiben sichtbar und führen
zu `ready=false`. Die CLI gibt dann Status 2 zurück. Ungefragte Komplettdownloads,
Weiterleitungen und geänderte ETags werden abgewiesen.

```bash
.venv/bin/python -m backtesting.slow_research freeze --output data/research/NEUER_VERSUCH
.venv/bin/python -m app.market_data.full_archive \
  --timeframe 4h --start 2023-01-01T00:00:00Z --end 2026-01-01T00:00:00Z \
  --output data/datasets/NEUER_DATENSATZ
.venv/bin/python -m backtesting.slow_research evaluate \
  --protocol data/research/NEUER_VERSUCH/protocol.json \
  --dataset data/datasets/NEUER_DATENSATZ --phase screen
```

Die aktuelle Quelle ist lückenhaft; diese Befehle umgehen die Sperre nicht.
Für eine spätere vollständige Quelle müssen Änderungen an Herkunft und Prüfplan
vor Ergebnisberechnung dokumentiert und neu eingefroren werden. Vorhandene Ordner
werden nie überschrieben. `--phase holdout` verlangt ein abgeschlossenes, zum
Protokoll und Datensatz passendes Screening; es prüft die einzelnen Ergebnisse
erneut, statt nur einem gespeicherten Erfolgsflag zu vertrauen.

Protokolle bewahren Python-Version, Quellenprüfsummen und eine Kopie aller
ausführbaren `app`-/`backtesting`-Dateien. Dashboard-Änderungen beeinflussen den
Forschungsstand nicht. Ältere Protokolle verweisen auf ihren damaligen Quellstand;
ein strikter Vergleich mit einem inzwischen erweiterten Projekt darf fehlschlagen.

Die Datenqualität darf vorab für den ganzen Zeitraum geprüft werden, die
Holdout-Performance nicht. Der Gate-Mechanismus ist keine Zugriffskontrolle für
Personen, die direkt die lokalen CSV-Dateien öffnen. Die Jahre liegen vor den
motivierenden 2026-Beobachtungen; selbst ein späteres positives Ergebnis wäre
eine rückblickende historische Prüfung, kein echter Vorwärtstest.
