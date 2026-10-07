# smtp-relay – Wiki

Anleitungen nach Themen. Für die Ersteinrichtung der Reihe nach durchgehen (1 → 5), danach ist jede Seite einzeln nutzbar.

| # | Seite | Inhalt |
|---|---|---|
| 1 | [Überblick](01-ueberblick.md) | Was das Relay macht, Aufbau, Sicherheitsprinzip |
| 2 | [Installation (Proxmox, Docker)](02-installation.md) | LXC oder VM vorbereiten, installieren, erster Login |
| 3 | [Microsoft 365 einrichten](03-microsoft-365.md) | Postfächer, App-Registrierung, Zertifikat, Sendeberechtigung (RBAC) |
| 4 | [Relay konfigurieren](04-relay-konfiguration.md) | Absender, Domains, SMTP-Konten, IP-Freigaben, Einstellungen |
| 5 | [Geräte anbinden](05-geraete-anbinden.md) | Einstellungen am Gerät, Hinweise je Gerätetyp, Test |
| 6 | [TLS und Zertifikate](06-tls.md) | Ports, STARTTLS/SMTPS, Zertifikat, Altgeräte |
| 7 | [Weitere Absender und Tenants](07-absender-und-tenants.md) | Gerät/Domain/Tenant hinzufügen, ändern, entfernen |
| 8 | [Betrieb](08-betrieb.md) | Updates, Backup und Wiederherstellung, Monitoring, Archiv, Admin-Reset |
| 9 | [Tests und Abnahme](09-tests.md) | Checkliste vor dem Produktivbetrieb |
| 10 | [Fehlersuche](10-fehlersuche.md) | Meldungen und ihre Ursachen |
| 11 | [Sicherheit](11-sicherheit.md) | Schutzmechanismen, Schlüssel, Restrisiken |
| 12 | [Öffentlich auf einem VPS](12-vps.md) | Relay ohne Kundenserver: öffentliche SMTP-Ports und Oberfläche, Let's Encrypt |

Beispielwerte in allen Seiten: Domain `kunde.de`, Relay `192.168.10.40` (DNS `smtp-relay.kunde.local`), App `smtp-relay-kunde`, Exchange-Scope `smtp-relay-absender` über `CustomAttribute10 = "smtp-relay"`.
