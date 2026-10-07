# 12. Öffentlich erreichbar auf einem VPS

Für Kunden ohne eigenen Server: Das Relay läuft auf einem VPS, die Geräte senden über das Internet. **Eine Instanz je Kunde.**

```
Geräte beim Kunden ──Internet, TLS (465 / 587)──▶ VPS: smtp-relay ──Graph──▶ Microsoft 365
Admin ──WireGuard-VPN──▶ VPS: Oberfläche (nicht öffentlich)
```

## Was anders ist als im Kundennetz

| Thema | Kundennetz | VPS |
|---|---|---|
| SMTP-Ports | 25, 465, 587 im LAN | nur **465 und 587**, öffentlich |
| Oberfläche | LAN (von außen über VPN des Kunden) | nur über **WireGuard auf dem VPS** |
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

## 1. Grundsystem und Firewall

```bash
apt update
apt full-upgrade -y
apt install -y ca-certificates curl git openssl ufw wireguard certbot
curl -fsSL https://get.docker.com | sh
```

Firewall (ufw regelt die Host-Dienste; die Docker-Ports sind über die Bindung auf bestimmte IPs begrenzt):

```bash
ufw default deny incoming
ufw allow 22/tcp
ufw allow 51820/udp
ufw allow 80/tcp
ufw enable
```

Port 80 nur für die Let's-Encrypt-Prüfung. SSH nach Möglichkeit nur mit Schlüssel bzw. nur über WireGuard.

## 2. WireGuard für die Oberfläche

```bash
cd /etc/wireguard
umask 077
wg genkey | tee server.key | wg pubkey > server.pub
```

`/etc/wireguard/wg0.conf`:

```ini
[Interface]
Address = 10.66.0.1/24
ListenPort = 51820
PrivateKey = <inhalt von server.key>

[Peer]
# Admin-Laptop
PublicKey = <öffentlicher Schlüssel des Laptops>
AllowedIPs = 10.66.0.2/32
```

```bash
systemctl enable --now wg-quick@wg0
```

Docker muss nach WireGuard starten, sonst kann die Oberfläche nach einem Neustart nicht an `10.66.0.1` binden:

```bash
mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nAfter=wg-quick@wg0.service\nWants=wg-quick@wg0.service\n' > /etc/systemd/system/docker.service.d/wireguard.conf
systemctl daemon-reload
```

Client (Laptop), z. B. WireGuard-App:

```ini
[Interface]
Address = 10.66.0.2/32
PrivateKey = <privater Schlüssel des Laptops>

[Peer]
PublicKey = <inhalt von server.pub>
Endpoint = relay-kunde.example.de:51820
AllowedIPs = 10.66.0.1/32
```

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
SMTP_TLS_HOSTNAME=relay-kunde.example.de
HTTP_BIND_HOST=10.66.0.1
HTTPS_BIND_HOST=10.66.0.1
```

## 4. Let's-Encrypt-Zertifikat

```bash
certbot certonly --standalone --http-01-address <öffentliche IP des VPS> -d relay-kunde.example.de --deploy-hook /opt/smtp-relay/deploy/letsencrypt-deploy-hook.sh
```

`--http-01-address` ist nötig: Die Oberfläche belegt Port 80 bereits auf der WireGuard-Adresse, certbot würde sonst auf allen Adressen binden wollen und scheitern. certbot merkt sich die Option für die Erneuerung.

Der Hook legt Zertifikat und Schlüssel unter `/opt/smtp-relay/smtp-tls/` ab und startet das Relay neu, sofern es schon läuft. certbot erneuert danach automatisch (systemd-Timer) und lädt das Relay über den Hook neu. Prüfen: `certbot renew --dry-run`.

## 5. Starten und einrichten

```bash
cd /opt/smtp-relay
docker compose up -d --build
docker compose ps
```

Mit aktivem WireGuard `https://10.66.0.1/` öffnen, weiter wie in [Installation 2.6](02-installation.md#26-erster-login), [Microsoft 365](03-microsoft-365.md) und [Relay konfigurieren](04-relay-konfiguration.md).

Geräte beim Kunden: Server `relay-kunde.example.de`, Port **465 SSL/TLS** (oder 587 STARTTLS), Zertifikatsprüfung **an** – das Let's-Encrypt-Zertifikat ist gültig.

## 6. Kontrolle von außen

Von einem Rechner außerhalb (nicht im VPN):

| Prüfung | Erwartet |
|---|---|
| `nc -vz relay-kunde.example.de 465` und `587` | offen |
| `nc -vz relay-kunde.example.de 25` | geschlossen |
| `nc -vz relay-kunde.example.de 443` | geschlossen (Oberfläche nur über VPN) |
| `openssl s_client -connect relay-kunde.example.de:465 -servername relay-kunde.example.de` | gültige Kette, `Verify return code: 0 (ok)` |
| Begrüßung | `220 relay-kunde.example.de ESMTP`, keine Softwareversion |

Danach die Checkliste [Tests und Abnahme](09-tests.md).
