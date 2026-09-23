# Nachtbericht, 23.09.2026

## Ergebnis zuerst

Es gibt derzeit **keine belastbar profitable Strategie und keine Handelsfreigabe**. Die getesteten Regeln schaffen den festgelegten Auswahltest mit normalen und erhöhten Kosten nicht. Die Ergebnisse sind rückblickende Entwicklungs- und Screeningtests auf bereits gesehenen Jahren; sie sind kein unabhängiger Nachweis für künftige Gewinne. 2025 wurde hinsichtlich Strategie-Performance weiterhin nicht ausgewertet.

## Was in der Nacht gebaut und geprüft wurde

Die Datenprüfung für zwei zuvor leere 4-Stunden-Intervalle wurde mit öffentlichen Kraken-Einzeltrades belegt. Es wurden keine künstlichen Kerzen ergänzt: In den überprüften Intervallen ohne veröffentlichte Trades gibt es keine simulierten Ein- oder Ausstiege, offene Positionen und Risikozustände bleiben erhalten, und ein Stop kann erst am ersten belegten Folge-Trade reagieren. Ungeprüfte Lücken bleiben gesperrt.

Danach wurden vier abgegrenzte Forschungsblöcke abgeschlossen: der 4-Stunden-Nettoziel-Filter, zwei langsamere Entwicklungshypothesen, die Übertragung fester Regeln auf eigene Bitvavo-Kurse sowie ein nachgezogener Stop. Zusammen liegen **68 abgeschlossene Forschungsläufe in sechs ausgewerteten Studien; zusätzlich ist der ursprünglich gesperrte Datenplan dokumentiert** vor. Die vollständige Suite ist mit **203 Tests grün**; zusätzlich wurden 106 Python-Quellen und das Dashboard-JavaScript syntaktisch geprüft. Die Datenbankergebnisse und SQLite-Integrität aller Läufe wurden abgeglichen.

## Ergebnisvergleich

Alle Beträge sind Netto-EUR auf einem jeweils getrennten 1.000-EUR-Jahreskonto, einschließlich der jeweiligen Kostenannahmen. 2023/2024 sind bereits gesehene Entwicklungsdaten und daher kein Holdout.

| Regel / Datenbasis | Normal 2023 / 2024 | Stress 2023 / 2024 | Befund |
| --- | ---: | ---: | --- |
| 4h-Nettoziel, Kraken aktuell | +34,34 / -6,99 | 0,00 / 0,00 | 2024 negativ; Stress ohne Trades |
| Langsamer Ausbruch, Kraken aktuell | +12,05 / -25,42 | -19,67 / -20,74 | beide Stressjahre negativ |
| Langsamer Ausbruch, Bitvavo | +43,29 / +15,22 | +30,17 / -1,66 | 2024 Stress negativ |
| Nachgezogener Stop, Bitvavo | +50,34 / +11,69 | +30,77 / -4,73 | 2024 Stress negativ; Kontrolle geschlagen nur teilweise |

Auch der Nettoziel-Filter auf Bitvavo war nicht konsistent: normal +88,12 / -25,37 EUR und Stress -0,72 / +14,44 EUR. Trend-Pullback blieb in den Bitvavo-Fällen negativ. Kein Kandidat ist in allen vier Jahres-/Kostenfällen positiv; deshalb wurde keiner ausgewählt oder automatisch für Paper Trading aktiviert. Kleine Tradezahlen und die getrennten Jahreskonten sind nur Arbeitskriterien, keine statistische Signifikanz. Höhere Kosten verändern durch andere Ausstiege und verworfene Signale auch die Tradeauswahl; ein gelegentlich besserer Stressfall ist daher kein Vorteil höherer Gebühren.

## Gebühren und Kostenrealität

Für einen Einstiegstarif ohne Rabatte wurden je Seite angesetzt: Kraken Pro 0,40 % Maker / 0,80 % Taker, Coinbase Advanced EU/UK 0,25 % / 0,50 % und Bitvavo EUR 0,15 % / 0,25 %. Bei einem Kauf und Verkauf mit jeweils 1.000 EUR entspricht das grob 16 EUR, 10 EUR beziehungsweise 5 EUR Taker-Gebühr. Dazu kommen Spread und Slippage. Die offiziellen Quellen sind [Kraken Gebührentabelle](https://www.kraken.com/features/fee-schedule) und [Kraken Änderung der Gebührenstufen](https://support.kraken.com/articles/cross-platform-fee-tier-changes), [Coinbase Ankündigung](https://www.coinbase.com/blog/were-lowering-fees-for-many-active-traders-on-coinbase-advanced) und [Coinbase Advanced Gebühren](https://help.coinbase.com/en/coinbase/trading-and-funding/advanced-trade/advanced-trade-fees) sowie [Bitvavo Gebühren](https://bitvavo.com/en/fees). Die Bitvavo-Studien verwenden eigene Bitvavo-Kurse, aber heutige Kostenannahmen auf historischen Preisen. Fremdbrokergebühren auf Kraken-Kursen waren dagegen reine Sensitivitätsrechnungen und kein Broker-Backtest.

## Paper und abgeschlossene öffentliche Beobachtung

Der PAPER-Beobachter war ausdrücklich auf `no_trade` gestellt. In 140 Ereignissen gab es ein HOLD-Signal um 06:00 Berlin, aber 0 Orders, 0 Positionen, 0 Trades und 0 Pollfehler. Das virtuelle Eigenkapital blieb bei 1.000 EUR; der Prozess wurde um 07:45 Berlin pausiert. Eine Wiederaufnahme auf einer unabhängigen Datenbankkopie war erfolgreich, die Originaldatenbank blieb unverändert. Das belegt die Betriebsmechanik, keine Strategieprofitabilität.

**Beobachtung abgeschlossen:** Der Quote-Monitor erhielt 151 von 151 öffentlichen Beobachtungen erfolgreich und 0 Fehler zwischen 05:14:14 und 07:44:31 Berlin. Der Median-Spread lag bei 0,131621 Basispunkten (etwa 0,001316 %), das Maximum bei 0,394698 Basispunkten. Die kleinste sichtbare Ask-Notionalmenge betrug nur 7,67 EUR; ein kleiner angezeigter Spread ist deshalb kein Beleg für günstige Fills größerer Orders. Die Stichprobe ist kurz, hat keinen Exchange-Event-Zeitstempel und belegt weder typische noch historische Spreads.

## Verbleibende Grenzen und nächste Schritte

Die vorhandenen Auswahlverfahren und Gates wurden angewendet, aber von keinem Kandidaten bestanden. Es fehlt eine längerfristige Spread- und Liquiditätsmessung. Der Beobachtungsrunner funktioniert; eine Handelsstrategie ist für den Dauerbetrieb noch nicht freigegeben. OHLC-Daten sind nicht tickgenau; ein Stop garantiert keinen Ausführungskurs. 2025 bleibt bis zu einer neuen, vorab registrierten Hypothese und einem bestandenen Gate zurückgehalten.

1. Eine neue, begründete Hypothese vorab registrieren und 2025 genau einmal als Holdout prüfen, ausschließlich nach bestandenem Gate und ohne nachträgliche Regeländerung.
2. Über längere Zeit Spreads, sichtbare Liquidität und Datenfrische öffentlich beobachten, bevor ein Ergebnis auf größere Orders übertragen wird.
3. Den Paper-Betrieb weiter als `no_trade` beobachten; eine Strategiefreigabe bleibt an unabhängige Daten-, Ausführungs- und Wiederaufnahmeprüfungen gebunden.

Die automatische Freigabeprüfung lehnte die geplante Umstellung auf einen Abschluss um 07:50 Uhr wegen des erreichten Nutzungslimits ab. Der Abschlussbericht wurde deshalb verspätet finalisiert.
