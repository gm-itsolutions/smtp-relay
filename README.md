# smtp-relay

SMTP-Relay für Geräte und Anwendungen im Firmennetz (Drucker, Scanner, NAS, USV, Proxmox, Fachanwendungen), das Mails über **Microsoft 365 (Graph API)** verschickt – ohne SMTP AUTH mit Passwort, das Microsoft ab Ende 2026 abschaltet.

Entwickelt und gepflegt von **GM IT Solutions** (Marvin Gawenda).

```
Geräte ──SMTP mit TLS (465 / 587 / 25)──▶ smtp-relay ──Graph sendMail──▶ Microsoft 365
```

## Sicher im Standard

- **Oberfläche:** TOTP Pflicht, Sperre nach Fehlversuchen, widerrufbare Sitzungen
- **Je Gerät:** eigenes Konto (an die IP gebunden) oder IP-Freigabe, jeweils nur mit dem eigenen Absender; Header-From muss stimmen
- **TLS immer an:** STARTTLS auf 25/587, SMTPS auf 465, Anmeldung nur verschlüsselt
- **Microsoft 365:** `Mail.Send` per RBAC nur für die Geräte-Postfächer
- **Datenschutz:** kein Mailarchiv im Standard
- **Container:** ohne root, read-only, lokal aus dem Quellcode gebaut; automatische Tests bei jedem Push

## Dokumentation

**[Wiki → docs/](docs/README.md)** – Installation, Microsoft 365, Konfiguration, Geräte, TLS, weitere Absender und Tenants, Betrieb, Tests, Fehlersuche, Sicherheit.

## Schnellstart

```bash
git clone https://github.com/gm-itsolutions/smtp-relay.git /opt/smtp-relay
cd /opt/smtp-relay
git checkout <aktueller Release-Tag>
# .env anlegen: siehe docs/02-installation.md
docker compose up -d --build
```

Danach [Microsoft 365 einrichten](docs/03-microsoft-365.md) und [Relay konfigurieren](docs/04-relay-konfiguration.md).

## Entwicklung

```bash
pip install -r ui/requirements.txt -r relay/requirements.txt pytest
python -m pytest -q
```

## Lizenz

MIT – siehe [LICENSE](LICENSE). Schwachstellen bitte vertraulich melden: [SECURITY.md](SECURITY.md).
