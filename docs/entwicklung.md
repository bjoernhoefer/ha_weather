# Entwicklungsablauf und Persona-Auswahl

## Ziel

Dieses Projekt nutzt GitHub Spec Kit für nachvollziehbare Anforderungen,
Planung und Aufgaben bei größeren Änderungen. Fünf Copilot-Agentenprofile
liefern gezielte fachliche Perspektiven. Sie sind keine fünf obligatorischen
Freigabeschritte: Die betroffenen Rollen werden nach Umfang und Risiko
ausgewählt.

Die Profile liegen unter [`.github/agents/`](../.github/agents/). Sie sind
Anweisungen für KI-Agenten und ersetzen weder Maintainer-Entscheidungen noch
echte meteorologische oder Home-Assistant-Fachprüfung.

## Automatische Triage

Copilot klassifiziert jede Umsetzungsanfrage anhand des Verhaltens- und
Betriebsrisikos, nicht nur anhand der Anzahl geänderter Dateien. Die Regeln
stehen in [`.github/copilot-instructions.md`](../.github/copilot-instructions.md).

| Stufe | Beispiele | Ablauf |
| --- | --- | --- |
| **T0 – redaktionell** | Tippfehler oder Formatierung ohne Laufzeit-/Nutzerwirkung | Keine Persona aufrufen; Inhalt und Links direkt prüfen. |
| **T1 – klein und lokal** | Begrenzte Änderung ohne API-, Daten-, Provider- oder Oberflächenwirkung | Relevante Checkliste direkt anwenden; keinen Subagenten für eine Kleinigkeit starten. |
| **T2 – relevant** | Mehrdatei-Feature, nichttriviale Logik oder Änderung an API, Provider, Home Assistant, UI, Konfiguration oder Nutzer-Dokumentation | Nur zuständige Fachrollen beteiligen; Qualität und Dokumentation prüfen lassen. Spec Kit nutzen, wenn Anforderungen oder Kompatibilität festgehalten werden müssen. |
| **T3 – hohes Risiko** | Forecast-/Scoring-Semantik, Daten-/API-Vertrag, Persistenz, Authentifizierung, Deployment oder mehrschichtige Änderung | Vollständige Spec-Kit-Artefakte und alle fachlich zuständigen Rollen; Tests, Kompatibilität und offene Risiken explizit prüfen. |

Bei mehrdeutiger Auswirkung wird vorsichtiger eingestuft. Nur wenn die
Unklarheit eine Produktentscheidung, Kompatibilität oder ein erhebliches Risiko
verändern kann, wird die Maintainerin oder der Maintainer gefragt. Agenten
werden nicht als ausgeführt ausgegeben, wenn sie nicht tatsächlich konsultiert
wurden. Die Abschlussmeldung nennt kurz die Stufe und ob Rollen tatsächlich
aufgerufen oder nur inline berücksichtigt wurden.

Die Auswahl ist eine KI-gestützte Entscheidung anhand der Repository-Anweisungen,
keine technisch erzwungene CI-Sperre. Bei erweitertem Scope wird erneut
eingestuft; höheres Risiko hat Vorrang vor der Dateianzahl. Delegierte Personas
bleiben bei ihrer Aufgabe und starten keine weiteren Persona-Reviews.

## Rollenprofile und Auswahl

| Profil | Einsetzen, wenn ... | Nicht routinemäßig einsetzen, wenn ... |
| --- | --- | --- |
| [EUMETSAT-Spezialist](../.github/agents/eumetsat-specialist.agent.md) | EUMETSAT-Produkte/-Dienste, Meteosat/MTG, Satellitenbeobachtungen oder satellitengestütztes Nowcasting betroffen sind. | Es um generische Wetterprovider oder normalen Anwendungscode ohne Satellitenbezug geht. |
| [Python-Architektur](../.github/agents/python-architecture.agent.md) | Python-Backend, Provider, API/Service, Konfiguration, Scoring oder Speicherung geändert werden. | Es nur um Texte, UI oder HA-Anwendungsbeispiele ohne Python-Verhalten geht. |
| [Home Assistant](../.github/agents/home-assistant-enthusiast.agent.md) | REST-Sensoren, Payloads, Einheiten, Entity-Beispiele, Einrichtung oder Automationen betroffen sind. | Nur unabhängige Web-UI- oder Provider-Interna geändert werden. |
| [UI/UX](../.github/agents/ui-ux-developer.agent.md) | Webdarstellung, responsive Bedienung, Barrierefreiheit oder UI-Zustände geändert werden. | Nur ein Backend-/HA-Vertrag ohne Oberflächenwirkung geändert wird. |
| [Qualität und Dokumentation](../.github/agents/quality-documentation.agent.md) | T2/T3 oder ein Nutzervertrag, Nutzerverhalten, Betriebsschritt oder dazugehörige Dokumentation betroffen ist. | T0 oder eine unkritische T1-Änderung ohne Verhaltens-/Dokumentationseffekt vorliegt. |

Ein Profil kann als Unteragent zur begrenzten Planung oder Review eingesetzt
werden. Kleine Änderungen werden ohne separate Agenten erledigt und mit der
passenden fachlichen Checkliste inline geprüft. Für neue oder bereits
zweisprachig gepflegte Nutzeranleitungen sind Deutsch und Englisch
abzugleichen; interne Notizen benötigen keine Übersetzung.

## Spec-Kit-Ablauf

Einmalig gelten die [Projektgrundsätze](../.specify/memory/constitution.md).
Für neue, sinnvolle Features:

1. `/speckit-specify` – Nutzerziel, Akzeptanzkriterien und betroffene Flächen.
2. `/speckit-clarify` – offene Entscheidungen klären, sofern nötig.
3. `/speckit-plan` – Architektur, Kompatibilität, Triage-Stufe und ausgewählte
   Personas festhalten.
4. `/speckit-checklist` bei Unklarheit oder erhöhtem Risiko; danach
   `/speckit-tasks` – Aufgaben mit angemessenen Tests/Dokumentation ableiten.
5. `/speckit-analyze` bei Unsicherheit, erhöhtem Risiko oder erforderlichem
   Abgleich der Artefakte – Spec, Plan und Tasks auf Widersprüche prüfen.
6. `/speckit-implement` und `/speckit-converge` – umsetzen und auf fehlende
   Anforderungen prüfen, bis die Umsetzung konvergiert.

Ein isolierter Low-Risk-Fix benötigt keine Feature-Spec: Code untersuchen,
gezielt ändern und die passende Prüfung ausführen. Tests und Persona-Aufrufe
bleiben risikobasiert, auch wenn Spec Kit genutzt wird.

## Einrichtung und Pflege

Die eingecheckten Skills und Skripte stammen aus Spec Kit **1.1.1**; eine
globale Installation ist für ihre Nutzung nicht erforderlich. Für CLI-Befehle:

```bash
uvx --from specify-cli==1.1.1 specify version
```

Neue Copilot-Sessions lesen die Repository-Anweisungen und Agentenprofile ein.
Für die CLI ist gegebenenfalls ein Neustart nötig; mit `/agent` prüfen, ob
die fünf Profile angeboten werden. Persönliche Profile mit gleicher ID können
die Repository-Profile übersteuern. Die automatische Agentenauswahl wurde nicht
durch einen unbeaufsichtigten End-to-End-Copilot-Lauf nachgewiesen.

Vor Updates lokale Anpassungen an Constitution und Templates sichern und
danach den Diff prüfen. `.specify/feature.json` ist ein ignorierter,
checkout-lokaler Zeiger auf das aktive Feature, keine gemeinsame Projektvorgabe.

## EUMETSAT-Fachquellen

Die EUMETSAT-Rolle prüft das konkrete Produkt anhand offizieller Quellen und
unterscheidet Beobachtung, abgeleitetes Produkt und Modellprognose. Als
Einstieg dienen:

- [Meteosat Third Generation](https://www.eumetsat.int/meteosat-third-generation)
- [Nowcasting SAF](https://www.eumetsat.int/nwc-saf)
- [EUMETSAT User Portal und Produktdokumentation](https://user.eumetsat.int/)

Produktspezifische Abdeckung, Latenz, Auflösung, Qualität, Lizenz und
Attribution müssen für das tatsächlich verwendete Produkt verifiziert werden.
