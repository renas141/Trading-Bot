# Öffentlicher Kraken-Livemarktzugang, 06.10.2026

Der Bot kann jetzt neben Vierstundenkerzen und Minuten-Analytics auch den
öffentlichen PF_XBTUSD-Handelsstrom begrenzt und fortsetzbar lesen. Dieser Zugang
benötigt keine Zugangsdaten und besitzt keine Order- oder Transferfunktion.

## Geprüfter Abruf

Am 06.10.2026 wurden über 100 aufeinanderfolgende Seiten genau 10.000 eindeutige
Trades von 12:14:07 bis 13:24:03 UTC gesichert. Rohseiten, normalisierte CSV,
Quell-URLs und SHA-256-Prüfsummen liegen im lokalen, von Git ausgeschlossenen
Evidenzbereich.

| Kennzahl | Wert |
| --- | ---: |
| Trades | 10.000 |
| Erfasstes Volumen | 138,1533 BTC |
| Erfasster Gegenwert | 11.908.509,77 USD |
| VWAP | 86.197,79 USD |
| Preisbereich | 85.962–86.412 USD |
| Käuferinitiierte Trades | 4.857 / 64,0641 BTC |
| Verkäuferinitiierte Trades | 5.143 / 74,0892 BTC |
| Preisänderung im Ausschnitt | −28,04 Basispunkte |
| Gekennzeichnete Teilliquidationen | 8 |

Die acht Teilliquidationen wurden als eigener Ereignistyp erhalten. Sie werden
nicht als normale Fills umetikettiert. Der kurze Ausschnitt zeigt einen leicht
stärkeren Verkäuferfluss, ist aber weder ein Handelssignal noch ein
Profitabilitätsnachweis.

Zusätzlich verarbeitete der begrenzte Echtzeit-PAPER-Beobachter drei neue
öffentliche Quote-/Funding-Beobachtungen ohne Fehler. Wegen des unvollständigen
Forward-Screens blieb der Status `no_trade_waiting_for_validation`; es wurde keine
virtuelle oder reale Position eröffnet.

Der aktuelle öffentliche Vertragsabruf bestätigte PF_XBTUSD als handelbar, ohne
Preisdislokation oder Extremvolatilitätsstatus. Tick- und Mengenschritte stimmen
mit dem lokalen Modell überein; die erste EWR-Marginstufe entspricht weiterhin
maximal 10x. Die persönliche Produktberechtigung lässt sich daraus nicht ableiten.

## Wiederholbarer Aufruf

```bash
.venv/bin/python -m app.market_data.kraken_futures_trades \
  --output data/evidence/kraken_pf_xbtusd_recent_trades_NEUER_NAME \
  --pages 100
```

Jeder Lauf verlangt einen neuen Ausgabeordner. Pro Seite werden höchstens 100
Trades akzeptiert, insgesamt höchstens 100 Seiten. Falscher Host, anderes Produkt,
Weiterleitungen, übergroße Antworten, rückwärts springende Zeitreihen,
widersprüchliche Duplikate und unbekannte Trade-Arten führen zum Abbruch und zur
vollständigen Bereinigung des unvollständigen Laufs.

Der öffentliche Endpunkt stellt höchstens die letzten sieben Tage oder Daten seit
dem jüngsten Neustart des Handelsmotors bereit. Einzeltrades zeigen ausgeführten
Marktfluss, garantieren aber keine eigene Ausführung zu diesem Preis.
