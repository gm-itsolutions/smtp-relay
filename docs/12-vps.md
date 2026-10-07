# 12. Öffentlich erreichbar auf einem VPS

Für Kunden ohne eigenen Server: Das Relay läuft auf einem VPS, die Geräte senden über das Internet. **Eine Instanz je Kunde.**

```
Geräte beim Kunden ──Internet, TLS (465 / 587)──▶ VPS: smtp-relay ──Graph──▶ Microsoft 365
Admin ──Internet, HTTPS (443), Passwort + TOTP──▶ VPS: Oberfläche
```

## Was anders ist als im Kundennetz

| Thema | Kundennetz | VPS |
|---|---|---|
| SMTP-Ports | 25, 465, 587 im LAN | nur **465 und 587**, öffentlich |
| Oberfläche | LAN (von außen über VPN des Kunden) | **öffentlich auf 443**, geschützt durch Passwort + TOTP |
| Zertifikat | selbst signiert | **Let's Encrypt** mit echtem DNS-Namen |
| SMTP-Konten | an die Geräte-IP gebunden (`/32`) | an die **feste öffentliche IP** des Kunden binden, wenn vorhanden; sonst Passwort + TLS |
| IP-Freigaben | einzelne Geräte | nur die feste öffentliche IP des Kunden (`/32`) |
| *Allow plain*, TLS < 1.2 | für Altgeräte möglich | **gesperrt** (öffentlicher Modus) |

Der **öffentliche Modus** (`SMTP_PUBLIC_MODE=1`, durch `docker-compose.vps.yml` gesetzt) erzwingt das: kein unverschlüsseltes SMTP, IP-Freigaben nur als Einzeladresse, TLS mindestens 1.2.

Für alle Instanzen gilt zusätzlich: Verbindungsgrenzen (`SMTP_MAX_CONNECTIONS`, `SMTP_MAX_CONNECTIONS_PER_IP`), Leerlauf-Timeout, Sperre nach Fehlanmeldungen, neutrale Begrüßung ohne Softwareversion.

Altgeräte ohne TLS 1.2 können ein VPS-Relay nicht nutzen – für diese Kunden ein Relay im Kundennetz.

## Voraussetzungen

- VPS mit Debian 13, feste öffentliche IPv4, Standort EU
- DNS-A-Eintrag, z. B. `relay-kunde.example.de` → öffentliche IP
- Ausgehend nur HTTPS nötig (Microsoft Graph); gesperrtes ausgehendes Port 25 beim Hoster stört nicht

## Die öffentliche Oberfläche

Die Oberfläche ist auf dem VPS aus dem Internet erreichbar. Schutz:

- Passwort **und** TOTP, beides Pflicht
- Sperre der IP nach 5 Fehlversuchen (Passwort oder TOTP) für 30 Minuten (`UI_LOGIN_BAN_THRESHOLD`, `UI_LOGIN_BAN_DURATION_MIN`)
- Sitzungen laufen nach `SESSION_LIFETIME_HOURS` ab (hier 2 h) und lassen sich widerrufen
- gültiges Let's-Encrypt-Zertifikat, HSTS

Restrisiko: Es gibt keine zweite Schutzschicht vor der Anmeldung, und jeder Admin ist Vollverwalter. Deshalb:

- nur **ein** Admin-Konto, langes Passwort aus dem Passwortmanager, TOTP auf einem Gerät, das nur du hast
- *Audit* regelmäßig auf `login_fail` / `totp_fail` prüfen; die tägliche Zusammenfassung meldet gehäufte Fehlanmeldungen

## 1. Grundsystem und Firewall

```bash
apt update
apt full-upgrade -y
apt install -y ca-certificates curl git openssl ufw certbot
curl -fsSL https://get.docker.com | sh
```

Firewall für die Host-Dienste (die Docker-Ports 443/465/587 sind über die Bindung an die öffentliche IP geregelt – Docker umgeht ufw):

```bash
ufw default deny incoming
ufw allow 22/tcp
ufw allow 80/tcp
ufw enable
```

Port 80 nur für die Let's-Encrypt-Prüfung. SSH nur mit Schlüssel (`PasswordAuthentication no`).

## 3. Relay installieren

```bash
git clone https://github.com/gm-itsolutions/smtp-relay.git /opt/smtp-relay
cd /opt/smtp-relay
git checkout <aktueller Release-Tag>
```

`.env` wie in [Installation 2.4](02-installation.md#24-konfiguration-env), mit diesen Abweichungen:

```ini
COMPOSE_FILE=docker-compose.yml:docker-compose.vps.yml
SMTP_BIND_HOST=<öffentliche IP des VPS>
HTTPS_BIND_HOST=<öffentliche IP des VPS>
SMTP_TLS_HOSTNAME=relay-kunde.example.de
SESSION_LIFETIME_HOURS=2
```

## 4. Let's-Encrypt-Zertifikat

```bash
certbot certonly --standalone -d relay-kunde.example.de --deploy-hook /opt/smtp-relay/deploy/letsencrypt-deploy-hook.sh
```

Der Hook legt Zertifikat und Schlüssel für das Relay unter `/opt/smtp-relay/smtp-tls/` und für die Oberfläche unter `/opt/smtp-relay/smtp-tls/nginx/` ab und startet beide neu, sofern sie schon laufen. **Vor dem ersten Start ausführen**, sonst fehlt nginx das Zertifikat. certbot erneuert danach automatisch (systemd-Timer) und lädt das Relay über den Hook neu. Prüfen: `certbot renew --dry-run`.

## 5. Starten und einrichten

```bash
cd /opt/smtp-relay
docker compose up -d --build
docker compose ps
```

`https://relay-kunde.example.de/` öffnen, weiter wie in [Installation 2.6](02-installation.md#26-erster-login), [Microsoft 365](03-microsoft-365.md) und [Relay konfigurieren](04-relay-konfiguration.md).

Geräte beim Kunden: Server `relay-kunde.example.de`, Port **465 SSL/TLS** (oder 587 STARTTLS), Zertifikatsprüfung **an** – das Let's-Encrypt-Zertifikat ist gültig.

## 6. Kontrolle von außen

Von einem Rechner außerhalb:

| Prüfung | Erwartet |
|---|---|
| `nc -vz relay-kunde.example.de 465` und `587` | offen |
| `nc -vz relay-kunde.example.de 25` | geschlossen |
| `nc -vz relay-kunde.example.de 443` | offen, gültiges Zertifikat im Browser |
| `https://relay-kunde.example.de/login/totp/enrol` nach Passwort-Login | kein QR-Code |
| 5× falsches Passwort | danach `Too many failed attempts` |
| `openssl s_client -connect relay-kunde.example.de:465 -servername relay-kunde.example.de` | gültige Kette, `Verify return code: 0 (ok)` |
| Begrüßung | `220 relay-kunde.example.de ESMTP`, keine Softwareversion |

Danach die Checkliste [Tests und Abnahme](09-tests.md).
