# 10. Fehlersuche

Der Grund einer Ablehnung steht fast immer im *Audit* der Oberfläche.

## Meldungen beim Gerät

| Gerät sieht | Audit-Grund | Lösung |
|---|---|---|
| `530 Authentication required` | – | Konto am Gerät fehlt, oder IP nicht freigegeben |
| `538 Encryption required` | – | Anmeldung ohne TLS: Port 465 (SSL/TLS) oder STARTTLS einschalten |
| `530 Must issue a STARTTLS command first` | `TLS required for this client` | Freigegebenes Gerät sendet unverschlüsselt: TLS am Gerät aktivieren oder *Allow plain* an der Freigabe |
| `535 Authentication failed` | `ip_not_allowed_for_user` / invalid credentials | Falsches Passwort oder Geräte-IP nicht in *Allowed source IPs* |
| `550 Sender not authorized` | `sender not authorised` | Adresse fehlt unter *Authorised senders* |
| `550 Sender not authorized` | `sender not allowed for this client` | Adresse fehlt bei *Allowed senders* des Kontos/der Freigabe |
| `550 Sender not authorized` | `sender domain not mapped…` | Domain unter *Domains* zuordnen |
| `550 Header From must match MAIL FROM` | `header From differs…` | Absenderadresse am Gerät = Postfachadresse setzen |
| `552 Too much mail data` | – | Mail größer als `SMTP_MAX_MESSAGE_SIZE` (30 MB) |
| `452 Rate limit exceeded` | `rate_limit_exceeded` | Gerät sendet zu viel; Ursache prüfen oder Limit anheben |
| `421 Connection refused` bzw. `550 Access denied` | Ban | IP/Konto gesperrt: *Config → Bans* |
| Zertifikatsfehler am Gerät | – | Zertifikatsprüfung aus oder eigenes Zertifikat ([TLS](06-tls.md)) |

## Mail hängt oder ist `dead`

| Fehler in der Queue | Ursache |
|---|---|
| Graph `403` / access denied | Postfach nicht im Exchange-Scope (`CustomAttribute10` fehlt) oder RBAC-Cache noch nicht aktualisiert (bis 2 h) – danach *Retry* |
| `AADSTS700027` / Zertifikatsfehler | `.cer` nicht in Entra hochgeladen oder neues Zertifikat aktiviert, ohne es hochzuladen |
| `AADSTS700016: Application was not found` | falsche Client ID oder Tenant ID |
| `AADSTS7000215: Invalid client secret` | (nur bei Secret statt Zertifikat) Secret falsch oder abgelaufen |
| bleibt `pending` | Graph nicht erreichbar oder App defekt: App prüfen, *Test connection*, dann *Retry* |

## Installation und Start

| Symptom | Lösung |
|---|---|
| `ENCRYPTION_KEY is not set` | `.env` fehlt oder Variable leer |
| UI startet neu / „Schema not ready" | `docker compose logs ui`; Migration nachholen: `docker compose run --rm ui alembic -c ui/alembic.ini upgrade head` |
| Freigegebenes Gerät bekommt `530`, Audit zeigt `172.28.x.x` | Relay sieht die Docker-Adresse statt der Geräte-IP: nicht vom Relay-Host selbst testen; Docker-Netz nie freigeben |
| Oberfläche zeigt nach Update altes Verhalten | Browser-Cache leeren (Strg+Umschalt+R) |
| `Connect-ExchangeOnline`: `Unable to find type […]` | PowerShell zu alt für das Modul, siehe [Microsoft 365, 3.1](03-microsoft-365.md#31-powershell-vorbereiten) |
