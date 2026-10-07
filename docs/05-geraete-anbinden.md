# 5. Geräte anbinden

## 5.1 Einstellungen am Gerät

| Einstellung | Gerät mit Konto | Gerät ohne Anmeldung |
|---|---|---|
| SMTP-Server | `smtp-relay.kunde.local` oder IP | dto. |
| Port / Verschlüsselung | **465 SSL/TLS** (bevorzugt) oder 587/25 STARTTLS | 465 SSL/TLS oder 25 STARTTLS; nur mit *Allow plain*: 25 ohne |
| Zertifikatsprüfung | aus, oder `cert.pem` des Relays importieren ([TLS](06-tls.md)) | dto. |
| Anmeldung | Konto und Passwort | keine |
| Absender | **genau das eigene Postfach** | dto. |
| Anzeigename | aussagekräftig, z. B. „Scanner Empfang" | dto. |

Der Header-From muss dem Absender entsprechen – eine abweichende Anzeigeadresse lehnt das Relay ab.

## 5.2 Hinweise je Gerätetyp

| Gerätetyp | Hinweis |
|---|---|
| Drucker / Multifunktionsgeräte | Scan-to-Mail: Anhanggröße begrenzen (Relay max. 30 MB, Exchange 35 MB), PDF komprimiert, moderate DPI |
| NAS (Synology, QNAP) | Benachrichtigungen → E-Mail → benutzerdefinierter Anbieter, Port 465 SSL/TLS, Anmeldung mit Konto |
| USV-Netzwerkkarten (APC, Eaton) | oft alte Firmware: IP statt DNS, ggf. nur TLS 1.0/1.1 oder gar kein TLS → [Altgeräte](06-tls.md#altgeräte) |
| Proxmox VE / PBS | Benachrichtigungsziel SMTP: Server Relay, Port 465, Modus TLS, Anmeldung mit Konto; Matcher z. B. nur Fehler |
| Windows-Skripte | `Send-MailMessage` prüft das Zertifikat – eigenes Zertifikat einspielen oder ein Tool wie `swaks`/Mailkit verwenden |
| Fachanwendungen | Port 465 SSL/TLS bzw. 587 STARTTLS; Massenversand beachten (Rate Limit, Exchange-Limits) |
| Kameras / NVR | wie USV |

## 5.3 Test

Vom Gerät eine Testmail an eine interne und eine externe Adresse, dann im Relay:

- *Queue*: Status `sent`
- *Audit*: `smtp_relay_ok` mit der **echten Geräte-IP** (nicht `172.28.x.x`)

Ohne Gerät, z. B. vom Proxmox-Host:

```bash
swaks --server smtp-relay.kunde.local --port 465 --tls-on-connect --auth LOGIN --auth-user printer-a --auth-password '<passwort>' --from printer-a@kunde.de --to ich@kunde.de --header "Subject: Relay-Test SMTPS"
```

```bash
swaks --server smtp-relay.kunde.local --port 587 --tls --auth LOGIN --auth-user printer-a --auth-password '<passwort>' --from printer-a@kunde.de --to ich@kunde.de --header "Subject: Relay-Test STARTTLS"
```

Nicht aus dem Relay-Container/-Host selbst testen: dort sieht das Relay nur die interne Docker-Adresse.

Passwörter aus Testbefehlen danach nicht in Chats/Tickets kopieren (swaks zeigt sie zusätzlich Base64-kodiert an).
