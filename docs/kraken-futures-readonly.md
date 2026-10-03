# Nur-lesende Kraken-Derivate-Prüfung

Stand: 04.10.2026. Dieser Baustein prüft später die konkrete Kontoberechtigung,
Wallets, offenen Positionen und bisherigen Ausführungen. Er kann keine Order
erstellen, ändern oder löschen, kein Geld übertragen und keine
Hebeleinstellung verändern.

## Sicherheitsgrenze

Der Client akzeptiert ausschließlich vier fest eingebaute `GET`-Endpunkte:

- API-Schlüsselrechte;
- Konten und Wallets;
- offene Positionen;
- eigene Ausführungen.

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

## Lokaler Status

Ohne Zugangsdaten erfolgt kein Netzaufruf:

```bash
.venv/bin/python -m app.exchange.kraken_futures_readonly status
```

Für eine spätere einmalige Kontoprüfung müssen die beiden Variablen nur im
aktuellen Prozess vorhanden sein:

- `KRAKEN_FUTURES_API_KEY`
- `KRAKEN_FUTURES_API_SECRET`

Danach führt `verify` die Rechteprüfung und die drei Lesezugriffe aus:

```bash
.venv/bin/python -m app.exchange.kraken_futures_readonly verify
```

Die Ausgabe enthält nur die bestätigten Rechte und Anzahlen von Konten,
Positionen und Ausführungen. Sie enthält keine Schlüssel und keine Guthaben.
Aktuell sind keine Zugangsdaten eingerichtet; deshalb ist die technische
Anbindung fertig, aber die persönliche Kraken-Berechtigung noch nicht bestätigt.
