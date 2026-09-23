# Papierkonto nach Neustart wieder aufnehmen

`DurablePaperBroker` ist eine neue, explizit wählbare Ausführungskomponente für
PAPER. Sie ist offline und besitzt keine Börsenverbindung. Der normale Start
handelt weiterhin nicht automatisch; ein vollständiger laufender Strategie-/
Datenprozess ist damit noch nicht freigegeben.

Gespeichert werden Kontostand, offene Positionen, abgeschlossene Trades,
Gebührensumme und der vollständige Risikozustand. Dazu gehören bisheriger
Kontohöchststand, Tagesbeginn, letzter Bewertungszeitpunkt, tägliche Verlustsperre,
Drawdown-Sperre und Kill Switch. Ein Neustart setzt keine dieser Sperren zurück.
Nur der reguläre Wechsel des UTC-Tages kann die tägliche Sperre zurücksetzen.

Ledger und Zustand teilen sich eine Transaktion. Verschachtelte Vorgänge dürfen
keinen Zwischenstand einzeln festschreiben. Bei Fehlern werden Datenbank und
Arbeitsspeicher auf den Zustand vor der Operation zurückgesetzt. Die Wiederaufnahme
prüft Positionen, Orders, Trades, Kosten und Kontostand gegeneinander. Fehlende
Checkpoints alter Sessions werden nicht aus unvollständigen Daten erraten.

Jede Wiederaufnahme beansprucht eine neue Revisionsnummer. Ein noch laufender
alter Prozess kann danach keine weitere Bewertung oder Order speichern. Geänderte
Gebühren, Risikogrenzen oder Instrumente erfordern eine andere Session; Pfade und
Log-Level dürfen abweichen. Bereits gestoppte Sessions werden nicht fortgesetzt.

Für einen späteren Runner gilt: Signal, Ausführung und eigener Fortschrittsstand
müssen gemeinsam innerhalb von `broker.atomic()` gespeichert werden. Strategie-
Historie, ausstehende Signale, doppelte Kursereignisse und die Aktualität der
Daten sind Aufgaben dieses Runners. Diese Komponente allein löst sie nicht.

```python
from app.config.settings import Settings
from app.database.repository import Repository
from app.execution.durable_paper import DurablePaperBroker

settings = Settings()  # PAPER; realistische Kosten explizit konfigurieren
with Repository(settings.database_path) as repository:
    session_id = repository.start_session(
        settings.mode, settings.initial_capital, settings.symbol)
    broker = DurablePaperBroker(settings, repository, session_id)
    # session_id außerhalb des Prozesses aufbewahren.

with Repository(settings.database_path) as repository:
    broker = DurablePaperBroker.resume(settings, repository, session_id)
    print(broker.snapshot())
```

Geprüft: Wiederaufnahme nach Verbindungsende; offene/geschlossene Trades mit
Gebühren; Verlustsperren und Höchststand; veralteter zweiter Schreiber; Fehler
nach einem Exit vor Checkpoint; äußerer Rollback einschließlich Signal und Entry;
fehlende Orders; veränderte Kosten; beschädigter Checkpoint; gestoppte Sessions;
Migration vorhandener Datenbanken. Keine Zusage zur Verlustbegrenzung bei
Kurslücken: ein Stop garantiert keinen Ausführungskurs.

## Laufender Beobachter mit Kursereignissen

Zusätzlich ist `QuotePaperRunner` implementiert. Er verbindet den dauerhaften
Brokerzustand mit einem Ereignisjournal und dem zuletzt verarbeiteten Kerzenschluss.
Signal, mögliche Ausführung, Kontobewertung und Verarbeitungsfortschritt werden
zusammen gespeichert. Identische Ereignisse werden auch nach Neustart nicht doppelt
gebucht. Ein Test mit absichtlich abgebrochenem Ereignis-INSERT bestätigt den
vollständigen Rollback einschließlich Entry und Signal.

Der öffentlich erreichbare Start verwendet ausschließlich `NoTradeStrategy`:

```sh
.venv/bin/python -m app.paper_cli --output data/paper/mein_neuer_beobachter --count 3
.venv/bin/python -m app.paper_cli --output data/paper/mein_neuer_beobachter --resume --count 3
```

Kein API-Schlüssel, keine Kontoverbindung. Standard 1.000 EUR virtuell, 4h-Kerzen,
Bitvavo-Taker-Annahme 0,25 %, zusätzlich 5 Basispunkte Slippage. Der Spread stammt
hier aus beobachtetem Bid/Ask und wird nicht ein zweites Mal als fester Spread
berechnet. Nach dem begrenzten Prozesslauf bleibt die Sitzung wiederaufnehmbar;
das Beenden des Beobachters erzeugt keine künstliche Schlussliquidation.

Mechanik für spätere Paper-Strategien ist mit synthetischen Testsignalen geprüft:
Kauf anhand des nach Kerzenschluss beobachteten Ask, Verkauf anhand des Bid, jeweils
mit ungünstiger Slippage/Rundung. Stop-Lücken werden am beobachteten schlechteren
Bid behandelt; ein Zielausstieg bekommt keine bessere Ausführung als das Ziel.
Angezeigte Menge muss genügen; ansonsten keine erfundene Ausführung ohne Tiefe.
Aktuelle Mindestmengen/-beträge werden zusätzlich zu den gespeicherten Grenzen
geprüft. Änderungen des Preis-/Mengenschritts blockieren die Verarbeitung.

Neueinstiege erfordern vollständige abgeschlossene Kerzen und einen maximal
90 Sekunden alten Schlusskurs-Entscheid. Historische Signale vor Sitzungsaktivierung
werden nur zum Aufwärmen gelesen. Der Quote muss lokal innerhalb von fünf Sekunden
empfangen worden und beim Verarbeiten höchstens zehn Sekunden alt sein. Instrument-
Metadaten dürfen höchstens fünf Minuten alt sein. Alte, revidierte oder fehlende
Kerzen pausieren Einstiege. Frische Quotes können Schutzverkäufe weiterhin auslösen,
auch wenn die Kerzenversorgung ausfällt.

Diese Aktualitätsprüfungen beziehen sich auf lokale Anfrage-/Empfangszeiten: die
öffentliche Quelle liefert keinen Quote-Ereigniszeitstempel. Ein sekunden- oder
minutenweise pollender Paper-Runner ist keine Simulation latenzfreier Stops. Auch
angezeigte Quote-Mengen sind keine tatsächliche Füllzusage. Der Standard tätigt
daher weiterhin keine Käufe; er prüft zunächst Datenfluss und Wiederaufnahme.
