# Nachtbericht, 23.09.2026

## Ergebnis zuerst

Es gibt derzeit **keine belastbar profitable Strategie und keine Handelsfreigabe**. Die getesteten Regeln schaffen den festgelegten Auswahltest mit normalen und erhöhten Kosten nicht. Die Ergebnisse sind rückblickende Entwicklungs- und Screeningtests; sie sind kein unabhängiger Nachweis für künftige Gewinne. Der 2025-Perpetual-Holdout ist in beiden Kostenfällen gescheitert; 2026-Perpetual-Kursdaten bleiben unangetastet.

## Was in der Nacht gebaut und geprüft wurde

Die Datenprüfung für zwei zuvor leere 4-Stunden-Intervalle wurde mit öffentlichen Kraken-Einzeltrades belegt. Es wurden keine künstlichen Kerzen ergänzt: In den überprüften Intervallen ohne veröffentlichte Trades gibt es keine simulierten Ein- oder Ausstiege, offene Positionen und Risikozustände bleiben erhalten, und ein Stop kann erst am ersten belegten Folge-Trade reagieren. Ungeprüfte Lücken bleiben gesperrt.

Zusätzlich wurde ein getrenntes, ausschließlich simuliertes Bitcoin-Perpetual-Modell (`PF_XBTUSD`) mit LONG/SHORT, Funding, Margin, Liquidation und maximal 10x Hebel geprüft. Es besitzt keine private Börsenanbindung und sendet keine Orders. Insgesamt liegen nun **176 abgeschlossene Forschungsläufe in 16 ausgewerteten Studien sowie ein gesperrter Datenplan** vor. Die vollständige Testsuite wird nach jeder Erweiterung erneut geprüft; Python-Quellen und Dashboard-JavaScript werden zusätzlich syntaktisch kontrolliert. Die Datenbankergebnisse, Abschlussbelege und SQLite-Integrität wurden abgeglichen.

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

Für `PF_XBTUSD` existiert nun zusätzlich ein wiederaufnehmbarer öffentlicher
Kostenbeobachter. Ein echter Ein-Punkt-Test maß rund 0,119 Basispunkte Spread,
bei 10.000 USD rund 0,338 Basispunkte zusätzliche Kauf- und 0,262 Basispunkte
Verkaufsslippage. Bei einer Million USD waren es rund 1,330 beziehungsweise
2,543 Basispunkte. Der gemeinsame Kraken-Zeitstempel, Funding, Rohantworten und
Prüfsummen wurden gespeichert. Diese eine Minute prüft die Technik, nicht die
Repräsentativität der Werte. Eine zusätzliche Kalibrierungssperre verlangt
mindestens 360 erfolgreiche Minuten über sechs Stunden, geringe Ausfälle und
frische lückenarme Daten, bevor überhaupt ein nicht aktivierender
Kostenkandidat erzeugt werden kann.

**Perpetual-Beobachtung abgeschlossen:** 477 von 480 Versuchen waren über knapp
acht Stunden erfolgreich; die Fehlerquote betrug 0,625 %. Das Spread-p95 lag bei
0,119 Basispunkten. Für 10.000 USD lagen die Slippage-p95 bei 0,683 Basispunkten
im Kauf und 0,736 im Verkauf. Das Gate für einen nicht aktivierenden
Kostenkandidaten bestand. Die vollständige Auswertung steht im
[Kostenbericht](perpetual-cost-observation-2026-09-24.md).

## Perpetual-Holdout und zusätzliche Grenzen

Der zunächst positive Long-only-Entwicklungsfall scheiterte im einmaligen 2025-Holdout: **−19,06 USD normal und −34,40 USD im Stressfall bei jeweils 5 Trades**. Auch die nachgelagerten Regeln für Gewinnschutz, Zeit/Momentum, Wiedereinstiegspause und ATR-Trailing wurden nicht ausgewählt. Die klassische Donchian-Trendregel endete 2025 bei **−24,92 USD normal und −35,84 USD Stress bei 9 Trades**. Keine dieser Varianten ist für PAPER oder LIVE freigegeben.

Am 24.09. wurde außerdem eine eigenständige
[Dual-Horizon-Zeitreihen-Momentum-Regel](perpetual-tsmom-research-2026-09-24.md)
vor der Ergebnisberechnung eingefroren und erstmals mit den beobachteten
p95-Kosten geprüft. Sie war 2023/2024 positiv, scheiterte aber 2025 mit
−20,32 USD normal und −31,21 USD unter doppelten Kosten. 2026 blieb unangetastet.

Eine letzte kurzfristige Momentum-Regel mit festen 7-/28-Tage-Horizonten und
höchstens sieben Tagen Haltedauer scheiterte ebenfalls 2025: −38,90 USD bei den
beobachteten Kosten und −71,12 USD unter doppelten Kosten. Die
[vollständige Auswertung](perpetual-short-momentum-research-2026-09-24.md)
beendet diese Momentum-Forschungsfolge ohne Auswahl.

Als nächste, getrennte Datenstufe wurden öffentliche PF_XBTUSD-Regimereihen für
Open Interest, Aggressor-Fluss, Liquidationen, rollende Volatilität,
Long/Short-Verhältnis und CVD geprüft und lokal mit Rohantworten sowie
Prüfsummen gespeichert. 2024 und 2025 sind vollständig, die gemeinsame
2023-Abdeckung beginnt am 31. Mai. Die [Datendokumentation](perpetual-regime-data-2026-09-24.md)
beschreibt Abdeckung, Hashes und die zusätzliche Vierstunden-Verzögerung gegen
Lookahead. Diese Erweiterung ist noch kein weiterer Strategielauf.

Das Modell unterstützt echte signierte Funding-Reihen, aber historische API-Reihen für 2023–2025 fehlen; dafür wurden nachteilige Funding-Sensitivitäten verwendet. 2026-Perpetual-Kursdaten wurden weder geladen noch ausgewertet. Regimewerte aus 2026 wurden dagegen für die technische Datenprüfung bereits angesehen; ein vollständig blinder Regime-Zeitraum beginnt deshalb erst nach dem 24.09.2026. LIVE und Strategie-PAPER bleiben gesperrt. Der GitHub-Zugriff ist inzwischen repositorygebunden eingerichtet und der Stand auf `main` gesichert.

## Verbleibende Grenzen und nächste Schritte

Die vorhandenen Auswahlverfahren und Gates wurden angewendet, aber von keinem Strategiekandidaten bestanden. Der erste achtstündige Perpetual-Kostenlauf und sein Kalibrierungstor sind abgeschlossen; weitere Marktphasen fehlen weiterhin. Eine Handelsstrategie ist für den Dauerbetrieb noch nicht freigegeben. OHLC-Daten sind nicht tickgenau; ein Stop garantiert keinen Ausführungskurs.

1. Eine neue, begründete Hypothese vorab registrieren und erst nach bestandenem Gate auf späteren, unabhängigen Daten prüfen; keine nachträgliche Regeländerung.
2. Den bestandenen Kostenkandidaten in einer neuen vorab registrierten Replay-Studie verwenden und zusätzliche Beobachtungen über andere Tages-, Wochenend- und Volatilitätsphasen sammeln.
3. Den Paper-Betrieb weiter als `no_trade` beobachten; eine Strategiefreigabe bleibt an unabhängige Daten-, Ausführungs- und Wiederaufnahmeprüfungen gebunden.

Die automatische Freigabeprüfung lehnte die geplante Umstellung auf einen Abschluss um 07:50 Uhr wegen des erreichten Nutzungslimits ab. Der Abschlussbericht wurde deshalb verspätet finalisiert.
