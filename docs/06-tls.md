# 6. TLS und Zertifikate

TLS gehört zur Grundeinrichtung und lässt sich nicht abschalten.

## Ports

| Port am Host | Art | Am Gerät meist |
|---|---|---|
| 465 (`SMTPS_BIND_PORT`) | SMTPS – verschlüsselt ab dem ersten Byte | „SSL/TLS", „SSL" |
| 587 (`SMTP_SUBMISSION_PORT`), 25 (`SMTP_BIND_PORT`) | unverschlüsselt, dann STARTTLS | „STARTTLS", „TLS" |

Beide Wege sind gleich stark. STARTTLS ist nur sicher, wenn der Server TLS erzwingt – das tut das Relay:

- **SMTP-Konten** können sich nur über TLS anmelden (sonst `538 Encryption required`).
- **IP-Freigaben** verlangen TLS, solange *TLS required* angehakt ist (sonst `530 Must issue a STARTTLS command first`).

Mindestversion TLS 1.2.

## Zertifikat

Ohne weitere Konfiguration erzeugt das Relay beim ersten Start ein **selbst signiertes** Zertifikat (RSA 2048, 5 Jahre, Name = `SMTP_TLS_HOSTNAME`) und legt es im Daten-Volume unter `/data/smtp-tls/` ab. Es bleibt bei Neustarts und Updates gleich.

Was das bedeutet:

- Die Verbindung ist verschlüsselt – gegen Mitlesen im Netz geschützt.
- Ein Client kann nicht prüfen, ob er wirklich mit dem Relay spricht (kein Schutz gegen aktiven Man-in-the-Middle im LAN). Bei Druckern/USV üblich; die meisten prüfen ohnehin nicht.
- Testwerkzeuge melden „self-signed" bzw. bei Verbindung über die IP zusätzlich „host verification failed". Mit einem DNS-Eintrag auf `SMTP_TLS_HOSTNAME` und Verbindung über den Namen entfällt der zweite Hinweis.

### Eigenes Zertifikat (interne CA oder Let's Encrypt)

Für Geräte, die das Zertifikat prüfen:

1. `cert.pem` (inkl. Zwischenzertifikate) und `key.pem` nach `/opt/smtp-relay/smtp-tls/` legen, lesbar für UID 1000:
   ```bash
   chown 1000:1000 /opt/smtp-relay/smtp-tls/*.pem
   chmod 600 /opt/smtp-relay/smtp-tls/key.pem
   ```
2. In `docker-compose.yml` beim Dienst `relay` die Zeile `# - ./smtp-tls:/tls:ro` einkommentieren.
3. In `.env`:
   ```
   SMTP_TLS_CERT=/tls/cert.pem
   SMTP_TLS_KEY=/tls/key.pem
   ```
4. `docker compose up -d`

Let's Encrypt-Zertifikate laufen 90 Tage. Auf einem öffentlich erreichbaren Server erledigt das `deploy/letsencrypt-deploy-hook.sh` mit certbot ([VPS](12-vps.md#4-lets-encrypt-zertifikat)); im Kundennetz ohne öffentlichen Zugang per DNS-Challenge erneuern und `docker compose restart relay` ausführen.

### Selbst erzeugtes Zertifikat erneuern

Nach 5 Jahren bzw. bei geändertem Namen:

```bash
docker compose exec relay sh -c 'rm /data/smtp-tls/cert.pem /data/smtp-tls/key.pem'
docker compose restart relay
```

## Altgeräte

| Gerät kann | Lösung |
|---|---|
| nur TLS 1.0/1.1 | `SMTP_TLS_MIN_VERSION=1.0` in `.env` (gilt für das ganze Relay) – oder IP-Freigabe mit *Allow plain* |
| gar kein TLS | IP-Freigabe mit *Allow plain*, Port 25 ohne Verschlüsselung |
| nur Port 465 / nur STARTTLS | beides wird angeboten |

*Allow plain* nur in vertrauenswürdigen Netzsegmenten und in der Kundendokumentation vermerken.
