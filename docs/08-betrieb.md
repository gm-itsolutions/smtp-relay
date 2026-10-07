# 8. Betrieb

## Update

Änderungen des neuen Releases kurz lesen (Commits seit dem laufenden Tag), dann:

```bash
cd /opt/smtp-relay
git fetch --tags
git checkout <neuer Tag>
docker compose up -d --build
docker compose ps
```

Datenbank-Migrationen laufen automatisch, Daten und Konfiguration bleiben erhalten. Nach einem Update der Oberfläche ggf. den Browser-Cache leeren (Strg+Umschalt+R).

## Backup

Zu sichern sind das Volume `smtp-relay-data` (Datenbank, TLS-Zertifikat, ggf. Archiv) und `.env` mit `ENCRYPTION_KEY`.

- **Am einfachsten:** VM bzw. CT per Proxmox Backup Server sichern – enthält alles. PBS-Verschlüsselung aktivieren: Datenbank und Schlüssel liegen dann in derselben Sicherung.
- **Nur die Daten:**
  ```bash
  cd /opt/smtp-relay
  docker run --rm -v smtp-relay-data:/data:ro -v "$PWD":/backup alpine tar czf /backup/smtp-relay-data-$(date +%F).tgz -C / data
  ```

## Wiederherstellung

```bash
cd /opt/smtp-relay
docker compose down
docker volume create smtp-relay-data
docker run --rm -v smtp-relay-data:/data -v "$PWD":/backup alpine tar xzf /backup/smtp-relay-data-<datum>.tgz -C /
docker compose up -d
```

`.env` mit **demselben** `ENCRYPTION_KEY` muss vorhanden sein. Fehlt er: neues Zertifikat für die App erzeugen und in Entra hochladen, Admin per Reset (unten) zurücksetzen – Konten, Absender und Freigaben bleiben erhalten.

Wiederherstellung einmal üben: Sicherung als zweite VM/CT mit anderer IP zurückspielen, Login, *Test connection*, Testmail.

## Monitoring

- Externe Prüfung auf TCP 465 und 25 des Relays (RMM, Uptime-Monitor)
- Docker-Healthcheck des `relay`-Containers prüft beide SMTP-Ports
- Tägliche Zusammenfassung per Mail (*Config → Notifications*). Sie läuft über das Relay selbst – bleibt sie aus, ist das selbst ein Alarm.

## Warteschlange (*Queue*)

- `pending` → `sending` → `sent`; nach 3 Fehlversuchen `dead` (Wartezeiten 1, 5, 15 Minuten).
- **Retry** geht nur für nicht zugestellte Mails (`dead`, `failed`, `pending`). Bereits versendete lassen sich nicht erneut einreihen.
- Tote Einträge werden mit der Aufbewahrung der versendeten Einträge gelöscht.

## Mailarchiv und Datenschutz

**Standard: aus** (`ARCHIVE_ENABLED=0`). Nach der Zustellung bleibt keine Kopie der Mail, auch der Inhalt in der Queue-Zeile wird gelöscht. Nachweis der Zustellung über *Audit* und die Nachrichtenablaufverfolgung von Exchange Online.

`ARCHIVE_ENABLED=1` speichert jede zugestellte Mail als `.eml` (inkl. Anhänge) im Daten-Volume, unverschlüsselt, lesbar für jeden Admin der Oberfläche, Aufbewahrung mindestens 3 Tage. Nur einschalten, wenn Nachweise ausdrücklich gefordert sind – dann Aufbewahrung mit dem Verantwortlichen (Auftragsverarbeitung) festlegen.

Die Einstellung ist absichtlich nur über `.env` änderbar, nicht über die Oberfläche.

## Admin-Passwort oder TOTP verloren

1. In `.env`:
   ```
   ADMIN_RESET=1
   ADMIN_NEW_PASSWORD=<neues Passwort, ≥ 12 Zeichen>
   ```
2. `docker compose up -d ui`
3. Mit dem neuen Passwort anmelden; Passwortwechsel und TOTP-Einrichtung werden erzwungen.
4. **Zurücksetzen:** `ADMIN_RESET=0`, `ADMIN_NEW_PASSWORD=` leeren, `docker compose up -d`.

## Alle Sitzungen beenden

Neuen `SECRET_KEY` in `.env` setzen und `docker compose up -d` – alle sind abgemeldet. Einzelne Benutzer: *Config → Users* (deaktivieren, Passwort oder TOTP zurücksetzen beendet deren Sitzungen).
