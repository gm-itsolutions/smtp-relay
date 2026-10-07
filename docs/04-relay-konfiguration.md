# 4. Relay konfigurieren

Alles in der Oberfläche unter *Config*.

## 4.1 Grundeinstellungen (*Settings*)

| Einstellung | Empfehlung |
|---|---|
| SMTP authentication: Local accounts | an |
| SMTP authentication: IP whitelist | nur an, wenn es Geräte ohne Anmeldung gibt |
| Rate limiting | an, Bezug *Both*, z. B. 20 Mails / 60 s (Bremse bei Mailstürmen) |
| Logging: log mail contents | aus |
| Retention | Versendete Queue-Einträge 7 Tage, Audit 90 Tage; Archiv-Aufbewahrung greift nur bei `ARCHIVE_ENABLED=1` |

## 4.2 Domains (*Domains*)

Jede Absenderdomain der App zuordnen (`kunde.de` → Default-App) und **Refuse senders whose domain is not mapped** einschalten.

## 4.3 Erlaubte Absender (*Authorised senders*)

Globale Liste: **nur die Geräte-Postfächer**, keine ganzen Domains, keine echten Benutzer. Der Schalter oben auf der Seite, der die Prüfung abschaltet, bleibt aus.

## 4.4 SMTP-Konten (*SMTP accounts*) – bevorzugt

Ein Konto je Gerät:

| Feld | Wert |
|---|---|
| Username | wie das Gerät, z. B. `printer-a` |
| Password | zufällig, ≥ 24 Zeichen, im Passwortmanager |
| Allowed source IPs / CIDRs | genau die Geräte-IP als `/32` |
| Allowed senders | genau das eigene Postfach, eine Adresse pro Zeile |
| Enterprise apps | erscheint erst ab zwei Apps; dann nur die App des eigenen Tenants |

Konten melden sich **immer über TLS** an – Passwörter laufen nie im Klartext.

**Leeres *Allowed senders* heißt „alle Adressen der globalen Liste"**, nicht „keine". Für eine saubere Trennung je Gerät immer ausfüllen.

## 4.5 IP-Freigaben (*IP whitelist*) – nur für Geräte ohne Anmeldung

| Feld | Wert |
|---|---|
| IP | einzeln als `/32` (breiter als `/24` wird abgelehnt) |
| Allowed senders | eigenes Postfach |
| TLS required | angehakt; *Allow plain* nur für Altgeräte ohne jedes TLS (rot markiert) |

Bestehende Einträge lassen sich über **Edit** ändern (Absender, Beschreibung, TLS); die IP selbst nicht.

Nie das Docker-Netz (`172.28.0.0/24`) freigeben.

## 4.6 Wann eine Mail durchgeht

Alle drei Stellen müssen zustimmen:

1. Adresse steht unter *Authorised senders* (global)
2. Adresse steht bei *Allowed senders* des Kontos bzw. der Freigabe
3. Postfach ist in Exchange im Scope (`CustomAttribute10 = "smtp-relay"`)

Fehlt 1 oder 2: sofort `550 Sender not authorized`. Fehlt 3: das Relay nimmt an, Microsoft lehnt ab (`403`), die Mail landet als `dead` in der *Queue*.

## 4.7 Benachrichtigungen (*Notifications*)

Empfänger z. B. `helpdesk@<ihr-msp>`, Absender eines der Geräte-Postfächer. Danach **Send test alert**. Die tägliche Zusammenfassung meldet u. a. Zertifikatsablauf, tote Mails, Plattenplatz und gehäufte Fehlanmeldungen.

Weiter mit [Geräte anbinden](05-geraete-anbinden.md).
