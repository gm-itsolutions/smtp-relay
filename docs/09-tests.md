# 9. Tests und Abnahme

Vor dem Produktivbetrieb einmal durchgehen. Tests mit `swaks` von einem Rechner im LAN (nicht vom Relay-Host selbst).

## Funktion

- [ ] Testmail über 465 (SMTPS) und 587 (STARTTLS) wird zugestellt, intern und extern
- [ ] *Audit* zeigt die echte Absender-IP
- [ ] *Notifications → Send test alert* kommt an
- [ ] Anhang ~20 MB geht durch, > 30 MB wird mit `552` abgelehnt
- [ ] Nach Neustart der VM/des CT laufen alle Container von selbst, Login und Konfiguration sind da, TLS-Zertifikat unverändert
- [ ] Ein echtes Gerät (Drucker/NAS) sendet erfolgreich

## Sicherheit – alles muss scheitern

| Test | Erwartet |
|---|---|
| Absender, der nicht in den *Allowed senders* des Kontos steht | `550 Sender not authorized` |
| Header `From:` ≠ Absender (`--header "From: chef@kunde.de"`) | `550 Header From must match MAIL FROM` |
| Konto von einer anderen IP | `535 Authentication failed` |
| Ohne Konto und ohne Freigabe | `530 Authentication required` |
| Anmeldung ohne TLS (Port 25 ohne `--tls`) | `538 Encryption required` |
| IP-Freigabe mit *TLS required*, Versand ohne TLS | `530 Must issue a STARTTLS command first` |
| 5 falsche Passwörter | Sperre unter *Config → Bans* |
| **Postfach außerhalb des Exchange-Scopes** (z. B. eigenes) testweise in *Authorised senders* und *Allowed senders* eintragen und senden | Relay nimmt an, Mail wird `dead` mit Graph `403` – **danach Einträge wieder entfernen** |
| Oberfläche: nach Passwort-Login `/login/totp/enrol` aufrufen | kein QR-Code |
| Oberfläche aus einem Netz außerhalb VPN aufrufen | nicht erreichbar |

Der Test mit dem Postfach außerhalb des Scopes ist der wichtigste: Er beweist, dass Microsoft die Grenze durchsetzt, auch wenn das Relay falsch konfiguriert wäre.

## Wiederherstellung

- [ ] Sicherung als zweite Instanz mit anderer IP zurückgespielt, Login, *Test connection*, Testmail erfolgreich
