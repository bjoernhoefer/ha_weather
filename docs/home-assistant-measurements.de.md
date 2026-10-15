# Home-Assistant-Temperaturmessungen konfigurieren

Das Dashboard kann einen Außenfühler aus Home Assistant als reale
Beobachtungsquelle für einen Standort verwenden.

## Instanz hinzufügen und Sensor finden

1. Öffne **Real world measurements → Home Assistant instances**.
2. Trage die Home-Assistant-URL und einen Long-Lived Access Token ein und
   speichere die Instanz. Der Token wird auf dem ha_weather-Server gespeichert
   und danach nicht mehr angezeigt.
3. Wähle unter **Measurements** die Instanz und den Standort aus.
4. Suche nach einem Teil des Anzeigenamens oder der Entity-ID, zum Beispiel
   `Garten`, und wähle einen aktivierten Treffer aus.
5. Prüfe Standort und den Bereich **outdoor** und speichere die Messung.

Die Suche prüft aktuell verfügbare Zustands-Entities in Home Assistant. Sie
zeigt keine deaktivierten oder anderweitig nicht geladenen Einträge aus der
Entity Registry. Passende Nicht-Temperatur-Entities werden angezeigt, können
aber nicht ausgewählt werden. Aktivierbar sind nur `sensor`-Entities mit der
Geräteklasse Temperatur, einem numerischen aktuellen Zustand und einer
Celsius-Einheit (`°C` oder `C`). Der aktuelle Zustand dient nur zur Auswahl;
die aufgezeichnete Historie liefert die täglichen Beobachtungen.

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
