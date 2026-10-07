# 7. Weitere Absender und Tenants

## Gerät hinzufügen (neuer Absender, bestehender Tenant)

Ein Gerät = ein Postfach = ein SMTP-Konto (oder eine IP-Freigabe).

1. **Postfach** (Exchange Online PowerShell):
   ```powershell
   New-Mailbox -Shared -Name "NAS" -DisplayName "NAS Warnungen" -PrimarySmtpAddress nas@kunde.de
   Set-Mailbox -Identity nas@kunde.de -CustomAttribute10 "smtp-relay"
   Test-ServicePrincipalAuthorization -Identity "smtp-relay-kunde" -Resource nas@kunde.de
   ```
   `InScope True` (bis zu 2 h Cache). An der Rollenzuweisung ändert sich nichts.
2. **Relay → Authorised senders:** `nas@kunde.de`
3. **Zugang:** SMTP-Konto (`/32`, *Allowed senders* `nas@kunde.de`) – oder IP-Freigabe, siehe [Relay konfigurieren](04-relay-konfiguration.md)
4. **Firewall:** TCP 465 (bzw. 587/25) vom Gerät zum Relay
5. **Gerät einstellen** und testen: [Geräte anbinden](05-geraete-anbinden.md)

## Weitere Adresse für ein bestehendes Gerät

Die drei Stellen aus [4.6](04-relay-konfiguration.md#46-wann-eine-mail-durchgeht): Adresse in *Authorised senders*, beim Konto unter *Allowed senders* ergänzen, Postfach mit `CustomAttribute10 "smtp-relay"` markieren.

## Gerät ändern oder entfernen

- **Neue IP / neues Passwort / weitere Absender:** *SMTP accounts → Edit* bzw. *IP whitelist → Edit* (die IP einer Freigabe ist fest: neu anlegen, alte löschen).
- **Entfernen:** Konto bzw. Freigabe löschen, Adresse unter *Authorised senders* löschen, Postfach aus dem Scope nehmen:
  ```powershell
  Set-Mailbox -Identity nas@kunde.de -CustomAttribute10 $null
  ```
  Das Shared Mailbox erst löschen, wenn niemand mehr dessen Antworten/Unzustellbarkeitsberichte braucht.

## Weitere Absenderdomain (gleicher Tenant)

1. Domain ist in Microsoft 365 als akzeptierte Domain eingerichtet.
2. *Config → Domains*: Domain der App zuordnen.
3. Geräte wie oben mit Adressen der neuen Domain anlegen.

## Weiterer Tenant

Für einen zweiten Microsoft-365-Tenant (z. B. zweite Firma einer Gruppe). Für **verschiedene Kunden** stattdessen je Kunde eine eigene Relay-Instanz – das trennt Admin-Zugang, Audit-Log und Daten sauber.

1. Im neuen Tenant [Microsoft 365 einrichten](03-microsoft-365.md) komplett durchgehen (eigene App, Scope, Rollenzuweisung in **diesem** Tenant).
2. *Config → Enterprise apps → Add enterprise app*: Name des Tenants, Tenant ID, Client ID.
3. Auf der Seite der neuen App: **Generate certificate** → `.cer` im neuen Tenant hochladen → **Activate** → **Test connection**.
4. *Config → Domains*: alle Domains dieses Tenants der neuen App zuordnen.
5. Geräte anlegen; bei jedem SMTP-Konto *Only the apps selected below* → die App dieses Tenants.

## Zertifikat der App erneuern

Die tägliche Zusammenfassung warnt vorher. Auf der Seite der App: **Generate new certificate** → neues `.cer` in Entra hochladen → **Activate** → **Test connection** → Testmail → altes Zertifikat in Entra löschen. Bis zum Aktivieren läuft das alte weiter.
