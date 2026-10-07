# 2. Installation (Proxmox, Docker)

Das Relay läuft in einer Debian-VM oder einem LXC-Container mit Docker im Kundennetz. Ohne Server beim Kunden: [Öffentlich auf einem VPS](12-vps.md). Für Kunden ist eine **VM** die robustere Wahl; ein LXC geht ebenfalls (getestet), braucht aber `nesting` und `keyctl`.

Mindestens: 1 vCPU, 1 GB RAM, 8–10 GB Disk, **feste interne IP**.

## 2.1 LXC anlegen (PVE-Shell)

Werte in `<…>` anpassen (CT-ID, Storage, Bridge).

```bash
pveam update
pveam available --section system | grep debian-13
pveam download local <debian-13-vorlage>
pct create <ctid> local:vztmpl/<debian-13-vorlage> --hostname smtp-relay --cores 1 --memory 1024 --swap 512 --rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=<ip>/<maske>,gw=<gateway> --unprivileged 1 --features nesting=1,keyctl=1 --onboot 1 --password
pct start <ctid>
pct enter <ctid>
```

`--password` fragt das root-Passwort für die Proxmox-Konsole ab (Passwortmanager). Ohne Passwort kommt man nur per `pct enter` hinein.

Für eine **VM** stattdessen Debian 13 normal installieren; die Schritte ab 2.2 sind identisch.

## 2.2 Docker installieren

```bash
apt update
apt full-upgrade -y
apt install -y ca-certificates curl git openssl swaks
curl -fsSL https://get.docker.com | sh
docker run --rm hello-world
```

## 2.3 Herunterladen

Das Repository ist öffentlich – keine Schlüssel nötig.

```bash
git clone https://github.com/gm-itsolutions/smtp-relay.git /opt/smtp-relay
cd /opt/smtp-relay
git checkout <aktueller Release-Tag>
```

Den aktuellen Tag zeigt `git tag --sort=-creatordate | head -1`. Immer einen Tag auschecken, nie einfach `main` produktiv betreiben.

## 2.4 Konfiguration (`.env`)

```bash
cat > /opt/smtp-relay/.env <<EOF
ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n')
APP_NAME=smtp-relay <Kunde>
SESSION_LIFETIME_HOURS=2

# SMTP nur auf der LAN-IP des Relays
SMTP_BIND_HOST=<relay-ip>
SMTP_BIND_PORT=25
SMTP_SUBMISSION_PORT=587
SMTPS_BIND_PORT=465
SMTP_TLS_HOSTNAME=smtp-relay.<kunde>.local
SMTP_MAX_RECIPIENTS=20

# Oberfläche: LAN-IP des Relays; von außen nur über das VPN des Kunden
HTTP_BIND_HOST=<ui-ip>
HTTPS_BIND_HOST=<ui-ip>

# Kein Mailarchiv (Datenschutz), siehe Betrieb
ARCHIVE_ENABLED=0
ADMIN_RESET=0
ADMIN_NEW_PASSWORD=
EOF
chmod 600 /opt/smtp-relay/.env
cat /opt/smtp-relay/.env
```

**`ENCRYPTION_KEY` sofort im Passwortmanager sichern** – ohne ihn ist ein Backup der Datenbank wertlos (Begründung: [Sicherheit](11-sicherheit.md#schlüssel-in-env)). Alle Variablen mit Erklärung: `.env.example`.

Wichtig: `SMTP_BIND_HOST` und `HTTPS_BIND_HOST` nie auf `0.0.0.0` lassen. Von Docker veröffentlichte Ports umgehen Host-Firewalls (ufw u. ä.).

## 2.5 Starten

```bash
cd /opt/smtp-relay
docker compose up -d --build
docker compose ps
```

Der erste Build dauert einige Minuten. Alle drei Dienste müssen laufen, `relay` nach etwa einer Minute `healthy`.

## 2.6 Erster Login

```bash
docker compose logs ui | grep -A2 'temporary password'
```

`https://<ui-ip>/` öffnen (Zertifikatswarnung bestätigen – selbst signiert), als `admin` mit dem Startpasswort anmelden, **TOTP einrichten**, neues Passwort setzen (≥ 20 Zeichen, Passwortmanager).

**Kontrolle:** abmelden, nur mit Passwort anmelden, dann `https://<ui-ip>/login/totp/enrol` aufrufen – es darf **kein** QR-Code erscheinen.

Weiter mit [Microsoft 365 einrichten](03-microsoft-365.md).
