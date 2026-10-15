# Home-Assistant-Temperaturmessungen konfigurieren

Das Dashboard kann einen Außenfühler aus Home Assistant als reale
Beobachtungsquelle für einen Standort verwenden.

## Instanz hinzufügen und Sensor finden

1. Öffne **Real world measurements → Home Assistant instances**.
2. Wähle unter **Location** den Standort der Instanz, trage die Home-Assistant-URL und einen Long-Lived Access Token ein und
   speichere die Instanz. Der Token wird auf dem ha_weather-Server gespeichert
   und danach nicht mehr angezeigt.
3. Wähle unter **Measurements** die Instanz aus. Ihr zugeordneter Standort wird
   übernommen; eine zweite Standortauswahl entfällt.
4. Suche nach einem Teil des Anzeigenamens oder der Entity-ID, zum Beispiel
   `Garten`, und wähle einen aktivierten Treffer aus.
5. Prüfe den übernommenen Standort und den Bereich **outdoor**, verwende optional
   **Test** und speichere die Messung.

Die Suche prüft aktuell verfügbare Zustands-Entities in Home Assistant. Sie
zeigt keine deaktivierten oder anderweitig nicht geladenen Einträge aus der
Entity Registry. Passende Nicht-Temperatur-Entities werden angezeigt, können
aber nicht ausgewählt werden. Aktivierbar sind nur `sensor`-Entities mit der
Geräteklasse Temperatur, einem numerischen aktuellen Zustand und einer
Celsius-Einheit (`°C` oder `C`). Der aktuelle Zustand dient nur zur Auswahl;
die aufgezeichnete Historie liefert die täglichen Beobachtungen.

## Testen und letzte Werte ansehen

Mit **Test** im Messungsformular vor dem Speichern oder neben einer vorhandenen
Messung wird der aktuelle Zustand aus Home Assistant abgerufen. Nutzbar ist ein
endlicher numerischer `sensor`-Wert mit Geräteklasse Temperatur und Celsius-Einheit
(`°C` oder `C`). Das Ergebnis zeigt Wert und verfügbaren Zeitstempel; nicht
verfügbare, ungültige oder nicht unterstützte Werte gelten nicht als nutzbare
Temperaturen. Verbindungs-, Authentifizierungs- und Zeitüberschreitungsfehler
werden ohne gespeicherte Zugangsdaten angezeigt. Der Test speichert keine
Einstellungen und verändert keine Provider-Bewertung.

Klappe **History** einer Messung auf, um die gleitenden letzten **24 Stunden**
aus dem Home-Assistant-Recorder abzurufen. Der Abschnitt ist anfangs zugeklappt
und lädt erst beim Öffnen; über die Aktualisierung werden neuere Daten angefragt.
Werte enthalten Zeitstempel; fehlende oder unbrauchbare Aufzeichnungen werden
nicht erfunden. Dies ist die Recorder-Historie der Quelle, **kein Protokoll der
bereits an ha_weather gelieferten Werte**. Der Recorder muss die Entity
aufzeichnen; ein erfolgreicher Test des aktuellen Zustands garantiert keine
Historie. Ein leeres Ergebnis kann daher korrekt sein.

Abschnittsüberschriften bleiben ohne Dreiecksmarker anklickbar und per Enter oder
Leertaste auf- und zuklappbar.

## Bestehende Konfigurationen

Bestehende Messungen behalten ihre Standorte. Eine bisherige Instanz mit
Messungen an genau einem gültigen Standort kann diesen automatisch anzeigen.
Eine Instanz mit mehreren Standorten bleibt im Legacy-Modus, statt ihre Sensoren
unbemerkt zu verschieben. Löse widersprüchliche Zuordnungen vor einer
Standortkopplung auf; andernfalls wird die Änderung abgelehnt. Für das
vereinfachte Formular zum Hinzufügen von Messungen muss die Instanz zuerst einem
Standort zugeordnet sein. Umgebungsverwaltete Instanzen bleiben im UI
schreibgeschützt.

Ältere API-Clients dürfen für nicht gekoppelte Instanzen weiterhin einen
Messungsstandort übergeben. Bei gekoppelten Instanzen entfällt er oder muss dem
Instanzstandort entsprechen; ein abweichender Standort wird abgelehnt. Eine
Änderung der Kopplung darf weder bestehende Messungen unbemerkt verschieben noch
archivierte Beobachtungen neu zuordnen.

## Stündliche Quellen vergleichen

Nachdem Prognosen aktualisiert wurden, öffne **Hourly source comparison** im
Dashboard. Dort wird die Temperatur jeder archivierten Wetterquelle einzeln
mit jedem konfigurierten Home-Assistant-Außenfühler derselben Stunde verglichen.
Sensoren verschiedener Instanzen bleiben getrennt. Die Matrix zeigt eine
ausgewählte Stunde; die Detailtabelle listet alle Quellenpaare des gewählten
Zeitraums von 24, 48 oder 72 Stunden. Die Uhrzeiten folgen der Zeitzone des
Standorts.

Die Abweichung ist Prognose minus Messwert; der absolute Fehler wird separat
angezeigt. Die Bewertung lautet `Good` bis einschließlich 1 °C, `Check` über
1 °C bis einschließlich 2 °C und `Large` über 2 °C. Das sind beschreibende
Temperaturstufen, kein Provider-Ranking-Score. Fehlt ein Wert oder weist die
Home-Assistant-Historie keinen Celsius-Temperatursensor aus, sind Fehler und
Bewertung nicht verfügbar. `unavailable` und andere ungültige Zustände gelten
nicht als Messwerte.
Ein aufgezeichneter Wert wird weitergeführt, solange sich der Sensorzustand
nicht ändert; die Auswertung setzt keine zusätzliche Aktualitätsgrenze.

Verglichen werden nur quellenspezifische Prognosen, die nach Bereitstellung
dieser Funktion gesammelt wurden. Neue Stundenwerte bleiben bis zu 72 Stunden
erhalten; bestehende Konsenswerte lassen sich keinen einzelnen Providern
zuordnen und werden nicht rückwirkend ergänzt.

## Fehlerbehebung

- **Keine Treffer**: Suche nach einem anderen Teil des Anzeigenamens oder der
  Entity-ID. Eine Entity-ID kann weiterhin manuell eingegeben werden.
- **Suche fehlgeschlagen**: Prüfe URL und Token und ob ha_weather Home Assistant
  erreichen kann. Ein Suchfehler ändert keine gespeicherten Messungen.
- **Öffentliche Bereitstellung**: Trage zusätzlich den ha_weather-API-Schlüssel
  im Dashboard ein.

Verwende HTTPS bei Verbindungen über ein nicht vertrauenswürdiges Netzwerk.
Lokale Home-Assistant-URLs in einem vertrauenswürdigen privaten Netzwerk
bleiben möglich.
