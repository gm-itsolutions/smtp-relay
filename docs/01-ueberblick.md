# 1. Überblick

## Wozu

Microsoft schaltet die Anmeldung per Benutzername und Passwort an `smtp.office365.com` (SMTP AUTH mit Basic Auth) ab Ende Dezember 2026 standardmäßig ab. Drucker, Scanner, NAS, USV-Karten und Fachanwendungen, die so Mails verschicken, hören dann auf zu funktionieren.

Das Relay steht im Kundennetz, nimmt Mails der Geräte per SMTP an und verschickt sie über die **Microsoft Graph API** mit OAuth (Zertifikat). Auf den Geräten ändert sich nur der SMTP-Server.

```
Geräte ──SMTP mit TLS (465 / 587 / 25)──▶ smtp-relay ──HTTPS, Graph sendMail──▶ Microsoft 365
```

## Aufbau

Drei Docker-Container:

| Container | Aufgabe |
|---|---|
| `relay` | SMTP-Annahme (STARTTLS 25/587, SMTPS 465), Prüfungen, Warteschlange, Versand über Graph |
| `ui` | Verwaltungsoberfläche |
| `nginx` | HTTPS vor der Oberfläche |

Alle Daten (Datenbank, TLS-Zertifikat, optional Archiv) liegen im Docker-Volume `smtp-relay-data`, die Grundkonfiguration in `.env`.

## Sicherheitsprinzip: vier Schichten

| Schicht | Begrenzt | Wie |
|---|---|---|
| 1. Netz | Wer das Relay erreicht | SMTP nur auf der LAN-IP, Firewall nur für Geräte-IPs, Oberfläche nur über VPN/Tailscale |
| 2. Zugang je Gerät | Welches Gerät senden darf | SMTP-Konto mit Passwort **und** an die Geräte-IP gebunden – oder IP-Freigabe für Geräte ohne Anmeldung |
| 3. Absender je Gerät | Als welche Adresse dieses Gerät senden darf | *Allowed senders* je Konto/Freigabe, globale Absenderliste, Header-From = Absender |
| 4. Microsoft 365 | Als welche Postfächer die App überhaupt senden darf | RBAC for Applications: `Mail.Send` nur für markierte Geräte-Postfächer |

Schicht 4 ist der Rettungsanker: Selbst ein falsch konfiguriertes oder kompromittiertes Relay kann nicht als Geschäftsführer oder Buchhaltung senden.

Mehr dazu: [Sicherheit](11-sicherheit.md).
