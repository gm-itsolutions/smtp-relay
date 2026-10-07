# 3. Microsoft 365 einrichten

Ziel: Eine App-Registrierung, die per Zertifikat ein Token bekommt und **nur** als die markierten Geräte-Postfächer senden darf.

## 3.1 PowerShell vorbereiten

Benötigt: Exchange Online PowerShell (`ExchangeOnlineManagement`), Mitglied der Rollengruppe *Organization Management*.

- Modul **3.10 und neuer verlangt PowerShell 7.6.** Mit älterer PowerShell (z. B. 7.3/7.4) kommt `Unable to find type [Microsoft.Exchange.Management…]`. Dann PowerShell aktualisieren oder Modul 3.9.2 verwenden.
- Ohne Eingriff ins System, z. B. auf Fedora:
  ```bash
  podman run -it --rm mcr.microsoft.com/powershell:latest pwsh
  ```
  ```powershell
  Install-Module ExchangeOnlineManagement -RequiredVersion 3.9.2 -Scope CurrentUser -Force
  Import-Module ExchangeOnlineManagement -RequiredVersion 3.9.2
  ```
- Anmelden (unter Linux mit Gerätecode):
  ```powershell
  Connect-ExchangeOnline -UserPrincipalName <admin>@kunde.de -Device
  ```

## 3.2 Geräte-Postfächer

Ein **Shared Mailbox** je Absender (keine Lizenz nötig). Alle werden mit einem Merkmal versehen, über das die Sendeberechtigung läuft. Vorher prüfen, dass `CustomAttribute10` im Tenant frei ist:

```powershell
Get-Mailbox -ResultSize Unlimited | Where-Object CustomAttribute10 -ne "" | Select-Object PrimarySmtpAddress,CustomAttribute10
```

Leere Ausgabe = frei. Sonst ein anderes `CustomAttributeX` wählen und überall ersetzen.

```powershell
New-Mailbox -Shared -Name "Scanner Empfang" -DisplayName "Scanner Empfang" -PrimarySmtpAddress printer-a@kunde.de
Set-Mailbox -Identity printer-a@kunde.de -CustomAttribute10 "smtp-relay"
```

Unzustellbarkeitsberichte und Antworten landen in diesen Postfächern – jemandem Lesezugriff geben oder an den Helpdesk weiterleiten.

## 3.3 App registrieren (Entra Admin Center)

1. *App registrations → New registration*: Name `smtp-relay-kunde`, *Accounts in this organizational directory only*, keine Redirect URI.
2. **Application (client) ID** und **Directory (tenant) ID** notieren.
3. **Keine** API-Berechtigung hinzufügen und **keine** Admin-Zustimmung erteilen – insbesondere kein `Mail.Send`. Berechtigungen aus Entra und aus Exchange addieren sich; eine Zustimmung in Entra würde die Begrenzung aus 3.5 aushebeln.
4. *Enterprise applications → smtp-relay-kunde* → **Object ID** notieren.

| Wert | Woher | Gebraucht für |
|---|---|---|
| Application (client) ID | App registrations **oder** Enterprise applications (identisch) | Relay, `-AppId` |
| Directory (tenant) ID | App registrations | Relay |
| Object ID | **nur Enterprise applications** | `-ObjectId`, `-App` |

## 3.4 Zertifikat (in der Relay-Oberfläche)

1. *Config → Enterprise apps → Default*: Name, Tenant ID und Client ID eintragen, speichern.
2. **Generate certificate** (Laufzeit 2 Jahre) → `.cer` herunterladen.
3. Entra: *App registrations → smtp-relay-kunde → Certificates & secrets → Certificates → Upload certificate*.
4. Im Relay **Activate**, dann **Test connection**.

„Test connection" prüft **nur, ob ein Token kommt** – nicht, ob die App senden darf. Das zeigt erst 3.5 bzw. eine echte Testmail.

## 3.5 Sendeberechtigung nur für die Geräte-Postfächer (RBAC for Applications)

```powershell
New-ServicePrincipal -AppId <CLIENT_ID> -ObjectId <OBJECT_ID> -DisplayName "smtp-relay-kunde"
New-ManagementScope -Name "smtp-relay-absender" -RecipientRestrictionFilter "CustomAttribute10 -eq 'smtp-relay'"
New-ManagementRoleAssignment -Name "smtp-relay Mail.Send" -App <OBJECT_ID> -Role "Application Mail.Send" -CustomResourceScope "smtp-relay-absender"
```

Prüfen – Geräte-Postfach `True`, normales Postfach `False`:

```powershell
Test-ServicePrincipalAuthorization -Identity "smtp-relay-kunde" -Resource printer-a@kunde.de
Test-ServicePrincipalAuthorization -Identity "smtp-relay-kunde" -Resource chef@kunde.de
```

Microsoft übernimmt geänderte App-Rechte nach **30 Minuten bis 2 Stunden**.

## 3.6 Berechtigungen kontrollieren

Die Berechtigungen liegen an zwei Stellen, Entra zeigt nur eine davon:

- **Entra** (soll leer sein): *Enterprise applications → smtp-relay-kunde → Security → Permissions*. Steht dort `Mail.Send` (Application), die Zustimmung entfernen.
- **Exchange** (die eigentliche Berechtigung):
  ```powershell
  Get-ManagementRoleAssignment -RoleAssignee "smtp-relay-kunde" | Format-Table Name,Role,CustomResourceScope
  Get-ManagementScope "smtp-relay-absender" | Format-List Name,RecipientFilter
  Get-Mailbox -ResultSize Unlimited | Where-Object CustomAttribute10 -eq "smtp-relay" | Select-Object PrimarySmtpAddress
  ```
  Die letzte Abfrage zeigt, **als wen** das Relay senden darf.

Weiter mit [Relay konfigurieren](04-relay-konfiguration.md).
