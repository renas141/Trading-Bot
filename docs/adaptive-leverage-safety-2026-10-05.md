# Adaptiver Paralleltest und Hebelsicherheit, 05.10.2026

## Ergebnis dieser Arbeitsstufe

Der bestehende, ab 03.10.2026 laufende Forward-Kandidat wurde nicht verändert.
Für eine zweite, unabhängig zu beurteilende Variante sind Strategie,
Risikomanager, Replay, Prüfgrenzen und Startzeit vor dem ersten zulässigen
Datenblock festgeschrieben worden.

Damit sind noch keine Gewinne nachgewiesen. Die neue Variante darf frühestens
nach 180 neuen Vierstundenblöcken ausgewertet werden und kann höchstens einen
separaten PAPER-Kandidaten erzeugen. LIVE bleibt aus.

## Gefundene und behobene Modellgrenze

Das erste Derivatemodell berechnet die Liquidationsschwelle beim Einstieg. Eine
spätere Funding-Zahlung verändert zwar den Kontostand, verschiebt dort aber nicht
die gespeicherte Schwelle. Dieser Zustand bleibt im laufenden Versuch aus
Integritätsgründen unverändert.

Die zweite Version berechnet deshalb bei jeder Bewertung neu:

- zugewiesene Positionsmargin plus unrealisierten Gewinn oder Verlust;
- bereits gezahltes oder empfangenes Funding;
- Maintenance Margin zum aktuellen Mark-Preis;
- Reserve für die Liquidationsgebühr;
- daraus verbleibende Margin und die dynamische Liquidationsschwelle.

Eine hohe adverse Funding-Zahlung kann jetzt auch bei flachem Kurs eine
Liquidation auslösen. Diese wird im Ergebnis ausdrücklich gezählt.

## Öffnen, Halten und Schließen bei 1x bis 10x

Automatisierte Lebenszyklustests öffnen und schließen LONG- und SHORT-Positionen
für jeden ganzzahligen Hebel von 1x bis 10x. Zusätzlich werden folgende Fälle
geprüft:

- normale Schließung einer stressfesten 10x-Position;
- Stop-Ausführung und Kurslücke;
- dynamische Liquidation nach Funding;
- automatische Verringerung von Positionsgröße und Hebel bei einem größeren
  angenommenen Kursloch;
- Ablehnung, wenn kein stressfester Ausstieg vor der Liquidationsschwelle bleibt.

Der Hebel vergrößert nicht automatisch das erlaubte Verlustrisiko. Der Manager
wählt für die nach allen Grenzen verbleibende Menge den kleinsten sicheren
ganzzahligen Hebel. 10x wird nur verwendet, wenn die Position sämtliche
Margin-, Funding- und Kurslückenprüfungen besteht.

## Neue Entscheidungsregel

Der Preis muss weiterhin auf zwei und sieben Tage in dieselbe Richtung zeigen.
Danach werden vier zeitlich verzögerte Bestätigungen geprüft:

1. steigendes Open Interest über sieben Tage;
2. richtungsgleicher Aggressor-Handelsfluss;
3. richtungsgleiche Veränderung des CVD;
4. keine Verschlechterung des richtungsbezogenen Fundings gegenüber den
   vorherigen 24 Stunden.

Bei weniger als drei Bestätigungen wird nicht gehandelt. Drei Bestätigungen
erlauben höchstens 0,5 Prozent normales Stop-Risiko. Nur vier Bestätigungen
erlauben 1,25 Prozent. Die höhere Stufe ist zusätzlich durch folgende gemeinsame
Stressgrenze begrenzt:

- zwei Prozent Kurslücke über den geplanten Stop hinaus;
- Ein- und Ausstiegsgebühren und nachteilige Ausführung;
- 0,002 Prozent adverses Funding je Vierstundenblock für maximal 42 Blöcke;
- zusammen höchstens drei Prozent Eigenkapitalverlust;
- mindestens fünf Prozent Eigenkapital als freie Reserve;
- maximal 10x und keine gestresste Liquidation vor dem angenommenen Ausstieg.

So entstehen mehr mögliche Signale, während das höhere Risiko ausschließlich
für vollständige Regelübereinstimmung verfügbar ist.

## Unveränderlicher zukünftiger Test

Die zuerst um 16:00 UTC vorgesehene v1 bleibt für die Auditspur erhalten, wird
aber nicht ausgewertet. Eine letzte Kontrolle fand vor ihrem Start, dass ein
neues Signal bei bereits offener Position einen zweiten Einstieg versuchen
konnte. Das eingefrorene v1-Protokoll wurde nicht überschrieben. Stattdessen
wurde eine korrigierte v2 vollständig neu und mit späterem Start gebunden.

In v2 werden weitere Einstiegssignale ignoriert, solange eine Position offen
ist. Screen-Kennzahlen verwenden ausschließlich Blöcke 1–180; Holdout-Kennzahlen
ausschließlich Blöcke 181–540.

- Protokoll: `pf-xbtusd-adaptive-funding-forward-v2`
- eingefroren: 05.10.2026, 15:59:25 UTC
- Forward-Start: 05.10.2026, 20:00 UTC
- Protokoll-SHA-256:
  `fa907d404c5ab39cbe5d41c693bb076d865ccab75f5241b2a10b43ab419a1687`
- gebundener Auswerter-SHA-256:
  `15b8280d95f87ca1b54450c40e9f5bfeea96d8a1e2343a03edd9a2700d307f27`
- gebundener Replay-SHA-256:
  `fbd42326a1cb8f230037671c1d4da66439ba189eff025c4f24c64b900f49aeb4`

Der 30-Tage-Screen benötigt 180 Blöcke und endet frühestens am 04.11.2026,
20:00 UTC. Nur wenn beide Kostenfälle die vorab festgelegten Gewinn-,
Profitfaktor-, Tradezahl-, Drawdown-, Liquidations- und Hebelgrenzen bestehen,
darf der 360-Blöcke-Holdout geöffnet werden. Dessen frühestes Ende ist der
03.01.2027, 20:00 UTC.

Der Paralleltest darf den Kandidaten vom 03.10.2026 weder ersetzen noch retten.
Es gibt keine nachträgliche Auswahl des besser aussehenden Verlaufs. Ein
bestandener Holdout wäre weiterhin nur die Berechtigung für längeres simuliertes
PAPER, keine Garantie künftiger Gewinne.
