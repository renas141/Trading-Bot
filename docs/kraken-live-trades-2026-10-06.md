# Öffentlicher Kraken-Livemarktzugang, 06.10.2026

Der Bot kann jetzt neben Vierstundenkerzen und Minuten-Analytics auch den
öffentlichen PF_XBTUSD-Handelsstrom begrenzt und fortsetzbar lesen. Dieser Zugang
benötigt keine Zugangsdaten und besitzt keine Order- oder Transferfunktion.

## Geprüfter Abruf

Am 06.10.2026 wurden fünf überschneidungsfreie Segmente mit jeweils 100 Seiten
gesichert. Der Gesamtbestand enthält genau 50.000 eindeutige Trades
von 07:33:45 bis 13:24:03 UTC. Rohseiten, normalisierte CSV-Dateien, Quell-URLs
und SHA-256-Prüfsummen liegen im lokalen, von Git ausgeschlossenen Evidenzbereich.

| Kennzahl | Wert |
| --- | ---: |
| Trades | 50.000 |
| Erfasstes Volumen | 854,1928 BTC |
| Erfasster Gegenwert | 73.492.420,73 USD |
| VWAP | 86.037,27 USD |
| Preisbereich | 85.379–86.412 USD |
| Käuferinitiierte Trades | 24.154 / 466,2581 BTC |
| Verkäuferinitiierte Trades | 25.846 / 387,9347 BTC |
| Preisänderung im Ausschnitt | +80,46 Basispunkte |
| Gekennzeichnete Liquidationsereignisse | 79 |

Die 78 Teilliquidationen und eine weitere Liquidation wurden als eigene
Ereignistypen erhalten. Sie werden nicht als normale Fills umetikettiert. Obwohl
mehr verkäuferinitiierte Einzeltrades auftraten, war das käuferinitiierte
BTC-Volumen größer. Der Ausschnitt ist weder ein Handelssignal noch ein
Profitabilitätsnachweis.

Die Einzeltrade-Seiten sind zeitbasiert paginiert und garantieren an den
Seitengrenzen keine vollständige Tickabdeckung. Für den vollständig enthaltenen
Vierstundenzeitraum 08:00–12:00 UTC umfasst die Stichprobe 641,3708 BTC. Krakens
separate Vierstunden-Analytics meldet 695,4585 BTC, entsprechend einer
Volumenabdeckung von 92,22 Prozent. Kaufvolumen überwog in beiden Quellen; die
Richtung ist damit konsistent, die Einzeltrade-Reihe bleibt aber ausdrücklich
eine große Stichprobe und kein vollständiges Marktband.

## Kurzfristige Vorhersageprüfung

Die Trades wurden zusätzlich in 24 ausreichend gefüllte 15-Minuten-Fenster
geteilt. Das käufer-/verkäuferinitiierte Volumenungleichgewicht korrelierte mit
der Preisbewegung desselben Fensters mit `0,425`. Für die Preisbewegung des
darauffolgenden Fensters sank die Korrelation jedoch auf `0,060`; die reine
Richtungsübereinstimmung betrug nur 47,83 Prozent. In einem Fenster lagen bis zu
36 Liquidationsereignisse.

Damit beschreibt das Ungleichgewicht den gerade laufenden Markt, liefert in
dieser Stichprobe aber keinen brauchbaren kurzfristigen Vorhersagevorteil. Es
wird deshalb nicht als neuer Einstiegsfilter in die eingefrorenen Strategien
eingebaut. Weitere zeitlich getrennte Stichproben dürfen diesen Befund später
erneut prüfen.

Zusätzlich verarbeitete der begrenzte Echtzeit-PAPER-Beobachter zehn neue
öffentliche Quote-/Funding-Beobachtungen im Minutenabstand ohne Fehler. Wegen des unvollständigen
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
Trades akzeptiert, insgesamt höchstens 100 Seiten. Mit `--before` und dem
`oldest_trade` des vorherigen Berichts kann das nächste ältere Segment ohne
Überschneidung geladen werden. Falscher Host, anderes Produkt,
Weiterleitungen, übergroße Antworten, rückwärts springende Zeitreihen,
widersprüchliche Duplikate und unbekannte Trade-Arten führen zum Abbruch und zur
vollständigen Bereinigung des unvollständigen Laufs.

Der öffentliche Endpunkt stellt höchstens die letzten sieben Tage oder Daten seit
dem jüngsten Neustart des Handelsmotors bereit. Einzeltrades zeigen ausgeführten
Marktfluss, garantieren aber weder vollständige Tickabdeckung noch eine eigene
Ausführung zu diesem Preis. Versuche an fünf älteren Tagesankern lieferten nach
dem jüngsten Handelsmotor-Neustart keine Daten und wurden vollständig verworfen.
