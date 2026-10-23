# Nur-lesende Kraken-Derivate-Prüfung

Stand: 23.10.2026. Dieser Baustein prüft die konkrete Kontoberechtigung,
Wallets, offenen Positionen und bisherigen Ausführungen. Er kann keine Order
erstellen, ändern oder löschen, kein Geld übertragen und keine
Hebeleinstellung verändern.

## Sicherheitsgrenze

Der Client akzeptiert ausschließlich fünf fest eingebaute `GET`-Endpunkte:

- API-Schlüsselrechte;
- Konten und Wallets;
- offene Positionen;
- eigene Ausführungen;
- die für das konkrete Konto zugänglichen Instrumente samt Mindestgröße und
  Einschränkungsstatus.

Vor dem Lesen des Kontos wird der Schlüssel selbst geprüft. Zulässig ist nur
`general = READ_ONLY` zusammen mit `transfer = NO_ACCESS`. Ein Schlüssel mit
`FULL_ACCESS` wird abgewiesen. Der Schlüssel und das Secret werden nur aus der
Prozessumgebung gelesen, weder gespeichert noch ausgegeben. Antworten sind
größenbegrenzt, Weiterleitungen sind deaktiviert und der feste HTTPS-Host ist
Teil der Prüfung.

Kraken dokumentiert für private Derivate-Aufrufe die Header `APIKey`, `Authent`
und optional `Nonce`. Die Signatur verwendet den kodierten Anfrageanteil,
Nonce und Pfad, SHA-256 sowie HMAC-SHA-512. Die Implementierung folgt dem
[offiziellen Derivatives-REST-Verfahren](https://docs.kraken.com/exchange/guides/futures/rest).
Die Rechte werden über Krakens
[API-Schlüsselprüfung](https://docs.kraken.com/api-reference/api-keys/check-v3-api-key)
bestätigt. Die erlaubten Inhalte entsprechen Krakens Dokumentation für
[Wallets](https://docs.kraken.com/api-reference/account-information/get-wallets),
[offene Positionen](https://docs.kraken.com/api-reference/account-information/get-open-positions)
und [eigene Ausführungen](https://docs.kraken.com/api-reference/historical-data/get-your-fills).
Die persönliche Produktfreigabe und Mindestgröße stammen später aus
[Get trading instruments](https://docs.kraken.com/api-reference/instrument-details/get-trading-instruments).

## Lokaler Status

Ohne Zugangsdaten erfolgt kein Netzaufruf:

```bash
.venv/bin/python -m app.exchange.kraken_futures_readonly status
```

## Kraken Pro einmalig vorbereiten

1. Im persönlichen Kraken-Konto den Derivatezugang vollständig abschließen. Für
   Kunden im EWR gehören dazu die Steuerangaben, TIN und Kundenklassifizierung.
2. Im Derivatekonto oben rechts den Namen öffnen, **Settings** wählen und im
   API-Bereich **Create Key** öffnen.
3. Einen eigenen Schlüssel nur für diese Prüfung anlegen: **General API = Read
   Only** und **Withdrawal API = No Access**.
4. Public und Private Key in einem Passwortmanager sichern. Das Private Key wird
   laut Kraken nur einmal angezeigt. Es gehört niemals in den Chat, in Git oder
   in eine unverschlüsselte Projektdatei.
5. Danach die folgende interaktive Prüfung im lokalen Projekt ausführen.

Die Schritte und Rechte entsprechen Krakens offizieller Anleitung für
[Derivate-API-Schlüssel](https://support.kraken.com/hc/articles/360022839451-how-to-create-an-api-key-for-kraken-derivatives).
Die EWR-Klassifizierung beschreibt Kraken unter
[How does classification work?](https://support.kraken.com/in/articles/how-does-classification-work).

Am einfachsten erfolgt die einmalige Kontoprüfung interaktiv. Beide Eingaben
bleiben im Arbeitsspeicher, werden im Terminal nicht angezeigt und nach Ende des
Prozesses verworfen:

```bash
.venv/bin/python -m app.exchange.kraken_futures_readonly verify-interactive \
  --output data/evidence/kraken-readonly/account-summary.json
```

Alternativ können die beiden Variablen nur im aktuellen Prozess vorhanden sein:

- `KRAKEN_FUTURES_API_KEY`
- `KRAKEN_FUTURES_API_SECRET`

Danach führt `verify` die Rechteprüfung und vier Konto-Lesezugriffe aus:

```bash
.venv/bin/python -m app.exchange.kraken_futures_readonly verify
```

Die Ausgabe enthält nur die bestätigten Rechte, Anzahlen von Konten, Positionen
und Ausführungen sowie Zugänglichkeit, Mindestgröße und Einschränkungsstatus von
`PF_XBTUSD`. Sie enthält keine Schlüssel und keine Guthaben.
Aktuell sind keine Zugangsdaten eingerichtet; deshalb ist die technische
Nur-Lese-Anbindung fertig, aber die persönliche Kraken-Berechtigung noch nicht
bestätigt. Für den Schlüssel sind ausschließlich **General READ_ONLY** und
**Transfer NO_ACCESS** zulässig. Ein Schlüssel mit Order- oder Transferrechten
wird vor dem Lesen des Kontos abgewiesen.

Ein späterer Handelsschlüssel wäre ein zweiter, getrennt erzeugter Schlüssel.
Er wird erst nach bestandenem Forward-Screen, unabhängigem Holdout und längerem
Shadow-PAPER-Lauf ergänzt. Auszahlungsrechte bleiben auch dann ausgeschlossen.
