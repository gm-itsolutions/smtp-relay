# 11. Sicherheit

## Schutzmechanismen

| Bereich | Umsetzung |
|---|---|
| Oberfläche | TOTP Pflicht; Sperre nach Fehlversuchen bei Passwort und TOTP; Sitzungen werden bei Abmelden, Passwortwechsel, TOTP-Reset und Deaktivieren beendet; Passwortwechsel beim ersten Login erzwungen; CSRF-Schutz, strikte CSP, sichere Cookies |
| SMTP-Zugang | Konto je Gerät, an die IP gebunden; IP-Freigaben höchstens `/24`; Sperre nach Fehlanmeldungen |
| Absender | Globale Liste + *Allowed senders* je Konto/Freigabe; Header-From muss Absender entsprechen |
| Transport | TLS immer an (STARTTLS, SMTPS), Anmeldung nur über TLS, mindestens TLS 1.2 |
| Microsoft 365 | Zertifikat statt Secret; `Mail.Send` per RBAC nur für markierte Postfächer; keine tenantweite Zustimmung |
| Daten | Kein Mailarchiv im Standard; Inhalte nach Zustellung gelöscht; Geheimnisse in der Datenbank verschlüsselt |
| Container | Kein root, read-only, alle Capabilities entfernt, `no-new-privileges`; Images lokal aus dem Quellcode gebaut |
| Qualität | Automatische Tests für die sicherheitsrelevanten Pfade laufen bei jedem Push |

## Schlüssel in `.env`

| Variable | Wofür | Verlust |
|---|---|---|
| `ENCRYPTION_KEY` | verschlüsselt in der Datenbank: privaten Schlüssel des App-Zertifikats, ggf. Client-Secret, TOTP-Secrets | Gespeicherte Geheimnisse unlesbar: neues Zertifikat erzeugen und hochladen, Admin zurücksetzen. **Nie ändern**, solange die Datenbank genutzt wird. Im Passwortmanager sichern. |
| `SECRET_KEY` | signiert Anmelde-Cookies und CSRF-Token | Unkritisch: neuen setzen, alle sind abgemeldet. Gezielt nutzbar, um alle Sitzungen zu beenden. |

## Restrisiken

- **Selbst signiertes Zertifikat:** schützt gegen Mitlesen, nicht gegen einen aktiven Angreifer im LAN, der sich als Relay ausgibt. Wo Geräte prüfen können: eigenes Zertifikat ([TLS](06-tls.md)).
- ***Allow plain*** an IP-Freigaben: Mails dieses Geräts laufen unverschlüsselt durchs LAN. Nur für Altgeräte, dokumentieren.
- **Alle Admins sind Vollverwalter:** Es gibt kein Rollenkonzept. Möglichst nur ein Admin-Zugang, Oberfläche nur über VPN.
- **Archiv eingeschaltet:** Mailinhalte liegen unverschlüsselt auf der VM.
- **Benachrichtigungen laufen über das Relay selbst:** Fällt es aus, kommt keine Warnmail – externes Monitoring einplanen.
- **Gemeinsame Limits:** Alle Geräte einer Instanz teilen sich Rate Limit und die Exchange-Grenzen der Postfächer.

## Schwachstellen melden

Siehe [SECURITY.md](../SECURITY.md).
