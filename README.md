# SMTP Relay — on-premise, Microsoft 365

An on-premise SMTP relay that lets your applications and devices send email through Microsoft 365 **without needing SMTP AUTH**.

> **GM IT Solutions fork** of [nicolafilippetto/smtp-relay](https://github.com/nicolafilippetto/smtp-relay) (v2.7.0, MIT). Changes, each covered by tests in `tests/`:
>
> - **TOTP bypass fixed:** `/login/totp/enrol` no longer re-displays an existing TOTP secret (upstream: password alone gave a full admin session).
> - **TOTP brute force:** wrong codes count towards the UI IP ban, and the ban is enforced on the TOTP step.
> - **Revocable sessions:** cookies carry `User.session_version`; logout, password change, TOTP reset and disabling a user revoke every session. `must_change_password` is enforced server-side.
> - **Per-client sender binding:** SMTP accounts and whitelist entries have *Allowed senders*; a device can only use its own `MAIL FROM`.
> - **Header From must equal MAIL FROM** (no display spoofing).
> - **Whitelist width:** entries wider than `/24` (IPv6 `/64`) are refused.
> - **Data minimisation:** `ARCHIVE_ENABLED=0` keeps no copy of delivered mail; DEAD queue rows are pruned with the sent-row retention.
> - **SMTP hardening:** size limit enforced while reading DATA; optional STARTTLS (`SMTP_TLS_CERT`/`SMTP_TLS_KEY`, `SMTP_AUTH_REQUIRE_TLS`).
> - **Deployment:** images are built locally from this checkout (no third-party registry, no `:latest`); relay healthcheck; Windows variant removed; Dependabot also for pip; CI runs the tests.
> - **Entra:** use RBAC for Applications to scope `Mail.Send` to the device mailboxes (see below) instead of tenant-wide consent.

---

## Why does this project exist?

Microsoft is retiring Basic Authentication for SMTP AUTH (username + password over SMTP) in **Exchange Online at the end of December 2026** ([official announcement](https://techcommunity.microsoft.com/blog/exchange/updated-exchange-online-smtp-auth-basic-authentication-deprecation-timeline/4489835)). After that date, any printer, scanner, legacy application, or internal tool that sends email via `smtp.office365.com` with a username and password will stop working.

This project solves the problem cleanly: instead of connecting to Office 365 over SMTP, it relays mail through the **Microsoft Graph API** using OAuth 2.0 Client Credentials. Your devices and applications talk to this relay over plain SMTP on your LAN — no code changes needed on their side.

**In short:** your devices keep sending email exactly as they do today. The relay handles the modern authentication with Microsoft 365 on their behalf.

---

## How it works

Three Docker containers, built locally from this repository:

| Service | Role |
|---------|------|
| `relay` | Accepts SMTP connections on your LAN (port 2525), queues messages, forwards them to Microsoft 365 via Graph API |
| `ui` | Web-based admin panel |
| `nginx` | TLS termination and reverse proxy for the UI |

All persistent data lives in Docker volumes — upgrades never touch your data.

---

## Quick start

On a Linux VM with Docker and the compose plugin:

```sh
git clone https://github.com/gm-itsolutions/smtp-relay.git /opt/smtp-relay
cd /opt/smtp-relay
git checkout <reviewed tag or commit>
cp .env.example .env
chmod 600 .env
# fill in ENCRYPTION_KEY and SECRET_KEY, bind SMTP/UI to the right addresses
docker compose up -d --build
```

On first boot the UI creates the database and generates a random `admin` password. Retrieve it with:

```sh
docker compose logs ui | grep -A2 'temporary password'
```

### 1. Open the UI

Browse to `https://<your-server-ip>/`. Accept the self-signed certificate warning and sign in as `admin`.

### 2. First-login setup

- Change the admin password (minimum 12 characters).
- Enrol TOTP (Google Authenticator, Aegis, Bitwarden, 1Password) by scanning the QR code.
- Enter the 6-digit code to confirm.

### 3. Configure Microsoft 365

*Config → Enterprise apps* — open the **Default** app and paste the Tenant ID, Client ID, and Client Secret from your Entra app registration (see [Microsoft Entra ID setup](#microsoft-entra-id-setup) below). Save, then click **Test connection**.

Sending from more than one Microsoft 365 tenant? See [Multiple tenants](#multiple-tenants).

### 4. Add authorised senders

*Config → Authorised senders* — add each mailbox address the relay is allowed to send *as*. Any `MAIL FROM` not on this list is rejected with `550 Sender not authorized`.

> A toggle at the top of that page can **disable the sender check entirely**, making the relay accept *any* `MAIL FROM`. This is a deliberately risky option (shown in red, with a confirmation) intended only as a temporary measure — it never bypasses SMTP authentication or the IP whitelist, only the From-address allow-list. The change is recorded in the audit log.

### 5. Configure SMTP client authentication

Two modes available under *Config → Settings* (at least one must be enabled):

- **Local credentials** — create SMTP accounts under *Config → SMTP accounts* and configure your devices with those credentials.
- **IP whitelist** — add trusted hosts (at most `/24`); devices from those IPs can send without credentials.

Prefer one SMTP account per device, bound to the device IP (*Allowed source IPs* `/32`) and to its own mailbox (*Allowed senders*). Use whitelist entries only for devices that cannot authenticate, and give them *Allowed senders* too.

### 6. Send a test message

Point an SMTP client on your LAN at `<your-server-ip>:2525` and send a test email. Watch it move through *Queue* (`pending → sending → sent`) and appear under *Archive*.

---

## Updating

Review the changes first (especially `ui/routers/auth.py` and `relay/`), then:

```sh
git fetch
git checkout <new reviewed tag>
docker compose up -d --build
```

Migrations run automatically. All data is preserved.

---

## Microsoft Entra ID setup

App registration and credential in the Entra admin center; the permission is granted in Exchange Online (step 4). No connectors, no transport rules.

1. **Register the application.**
   Entra admin center → *Applications* → *App registrations* → *New registration*.
   - Name: e.g. `smtp-relay`.
   - Supported account types: *Accounts in this organizational directory only*.
   - Redirect URI: leave blank.

2. **Copy the IDs.** From the Overview page, save:
   - *Directory (tenant) ID*
   - *Application (client) ID*

3. **Add a credential — choose one:** a client secret *or* a certificate.
   On the app's page under *Config → Enterprise apps*, pick the matching
   **Authentication method**.

   **Option A — Client secret** (simplest)
   *Certificates & secrets* → *Client secrets* → *New client secret*.
   - Set an expiry matching your rotation policy (e.g. 1 year).
   - **Copy the Value immediately** — it is only shown once. Paste it on the
     app's page and record its expiry date.

   **Option B — Certificate** (more secure, recommended)
   The relay generates the key pair for you, so the private key never leaves
   the deployment and its expiry is tracked automatically.
   1. On the app's page under *Config → Enterprise apps*, under
      **Certificate credential**, click
      **Generate certificate** (validity 1/2/3/5 years, default 5).
   2. **Download the `.cer`** and upload it in Entra:
      *Certificates & secrets* → *Certificates* → *Upload certificate*.
   3. Back on the app's page, click **Activate** — this promotes the staged
      certificate to the live credential. Generating never disrupts an
      in-use certificate, so rotation is zero-downtime: generate → upload →
      activate.

4. **Grant `Mail.Send` scoped to the device mailboxes (RBAC for Applications).**
   Do **not** add or consent `Mail.Send` under *API permissions*: Entra grants and Exchange RBAC grants are additive, so a tenant-wide consent would make the scope below useless. Instead, in Exchange Online PowerShell (member of *Organization Management*):

   ```powershell
   Set-Mailbox -Identity printer-a@contoso.com -CustomAttribute10 "smtp-relay"
   New-ServicePrincipal -AppId <client id> -ObjectId <enterprise app object id> -DisplayName "smtp-relay"
   New-ManagementScope -Name "smtp-relay-senders" -RecipientRestrictionFilter "CustomAttribute10 -eq 'smtp-relay'"
   New-ManagementRoleAssignment -App <enterprise app object id> -Role "Application Mail.Send" -CustomResourceScope "smtp-relay-senders"
   Test-ServicePrincipalAuthorization -Identity "smtp-relay" -Resource printer-a@contoso.com
   ```

   Use the *Object ID* from *Enterprise applications*, not from *App registrations*. Changes can take 30 minutes to 2 hours to apply.

5. Done. No SMTP AUTH configuration needed anywhere.

### Multiple tenants

A company with several Microsoft 365 tenants (for example one per branch)
can send through all of them from a single relay. An app registration can
only send as mailboxes of its own tenant, so the relay picks the app from
the sender's domain:

1. *Config → Enterprise apps* — add one enterprise app per tenant and set
   up each one as described above (its own app registration, credential and
   `Mail.Send` consent), then **Test connection**.
2. *Config → Domains* — map each sender domain to the app of its tenant.
   The **default app** handles every domain without a mapping; optionally,
   tick *Refuse senders whose domain is not mapped* to reject those instead.
3. Optionally, on an SMTP account, choose *Only the apps selected below*
   so that account can only send for the domains of those apps (for example
   so a branch's devices cannot send as another branch). Clients let in by
   the IP whitelist are not limited by this setting.

The relay picks the app when the client sends `MAIL FROM`, so a sender it
cannot route (or an account using an app it is not allowed to) is refused
right away with `550 Sender not authorized`; the reason is in the audit log.
The *Authorised senders* page shows which app each sender goes through.

Upgrading from a version with a single tenant needs no action: the existing
configuration becomes the default app, named *Default*, and the domains of
your authorised senders are mapped to it automatically.

---

## Day-to-day operation

- **Dashboard** — relay status, mail stats (24h/7d/30d), Graph token state per enterprise app, disk usage, recent audit events.
- **Queue** — filter by status (`pending / sending / sent / failed / dead`). Retry individual messages or all dead ones at once.
- **Archive** — browse by date, preview headers and body, download the raw `.eml`, or resend.
- **Audit log** — filter by event type, outcome, user, IP, date. Export as CSV.
- **Config** — all settings in one place: SMTP accounts, IP whitelist, authorised senders, enterprise apps, domains, notifications, users, global settings and bans.

---

## Admin password reset

If you lose the admin password or TOTP device:

1. Edit `.env`:
   ```
   ADMIN_RESET=1
   ADMIN_NEW_PASSWORD=<new password, min 12 chars>
   ```

2. Restart the UI container:
   ```sh
   docker compose up -d ui
   ```

3. Sign in with the new password — the UI forces a password change and fresh TOTP enrolment.

4. **Revert and restart:**
   ```
   ADMIN_RESET=0
   ADMIN_NEW_PASSWORD=
   ```
   ```sh
   docker compose up -d
   ```

---

## Hardening

**Network:** bind SMTP to a specific interface with `SMTP_BIND_HOST=<LAN-IP>` in `.env` — ports published by Docker bypass host firewalls such as ufw. Keep the UI behind a VPN (`HTTP(S)_BIND_HOST=<VPN-IP>`) — it is not designed to be internet-facing.

**STARTTLS for devices:** place `cert.pem`/`key.pem` in `./smtp-tls` (readable by uid 1000), uncomment the volume in `docker-compose.yml`, and set `SMTP_TLS_CERT=/tls/cert.pem`, `SMTP_TLS_KEY=/tls/key.pem`. With `SMTP_AUTH_REQUIRE_TLS=1` passwords are only accepted after STARTTLS.

**TLS:** replace the self-signed certificate by copying a real `fullchain.pem` and `privkey.pem` into the `smtp-relay-certs` volume:

```sh
docker run --rm \
    -v smtp-relay-certs:/certs \
    -v /path/to/real/certs:/real \
    alpine sh -c 'cp /real/fullchain.pem /certs/ && cp /real/privkey.pem /certs/'
docker compose restart nginx
```

**Containers run unprivileged:** every service (UI, relay, nginx) runs as a
non-root user with `cap_drop: ALL`, `no-new-privileges`, and a read-only root
filesystem. nginx uses the `nginxinc/nginx-unprivileged` image (uid 101) and
listens on 8080/8443 inside the container; the host ports stay 80/443.

> **Upgrading from a root nginx image:** if you relied on the auto-generated
> self-signed certificate, the existing `smtp-relay-certs` volume is owned by
> root and the new unprivileged nginx cannot read the private key. Re-own it
> once (real certificates you mount yourself are unaffected):
>
> ```sh
> docker run --rm -v smtp-relay-certs:/certs alpine chown -R 101:101 /certs
> docker compose up -d
> ```

---

## Retention

Three settings under *Config → Settings*:

| Setting | Default | Minimum enforced |
|---------|---------|-----------------|
| Archive retention | 30 days | 3 days |
| Audit log retention | 90 days | 30 days |
| Sent queue row retention | 30 days | none |

The minimums prevent an attacker who gains UI access from immediately erasing evidence.

DEAD queue rows are deleted together with sent rows. Set `ARCHIVE_ENABLED=0` in `.env` to keep no copy of delivered mail at all (the message content is also removed from the queue row once delivered). This is an environment variable on purpose: a UI account cannot change it.

---

## Backups

```sh
# Snapshot (database + archive):
docker run --rm \
    -v smtp-relay-data:/data:ro \
    -v "$PWD":/backup \
    alpine tar czf /backup/smtp-relay-data-$(date +%F).tgz -C / data

# Restore:
docker compose down
docker volume create smtp-relay-data
docker run --rm \
    -v smtp-relay-data:/data \
    -v "$PWD":/backup \
    alpine tar xzf /backup/smtp-relay-data-YYYY-MM-DD.tgz -C /
docker compose up -d
```

Back up `.env` too — without `ENCRYPTION_KEY` the saved client secret and certificate private key are unrecoverable.

---

## Troubleshooting

**`ENCRYPTION_KEY is not set`** — `.env` is missing or the variable is empty.

**UI keeps restarting / "Schema not ready"** — migration failed; check `docker compose logs ui`. Fix then run:
```sh
docker compose run --rm ui alembic -c ui/alembic.ini upgrade head
```

**`AADSTS7000215: Invalid client secret`** — secret is wrong or expired; generate a new one in Entra ID.

**`AADSTS700027: Client assertion contains an invalid signature` / certificate errors** — when using certificate auth, the public `.cer` was not uploaded to the app registration (or you activated a new certificate without uploading it first). Upload the certificate under *Certificates & secrets → Certificates*, then re-test on the app's page under *Config → Enterprise apps*.

**`AADSTS700016: Application was not found`** — wrong client ID or tenant ID.

**Message stuck in `pending`** — Graph connection is broken; the message's page under *Queue* shows which enterprise app it uses. Open that app under *Config → Enterprise apps*, fix and test, then retry the message from *Queue*.

**`530 Authentication required` from a whitelisted IP** — the relay sees the Docker bridge NAT address. Check the actual source IP in *Queue → \<row\>* and whitelist that.

**`550 Sender not authorized`** — address missing from *Config → Authorised senders* or disabled there.

**Lost admin password and TOTP** — see [Admin password reset](#admin-password-reset).

---

## About this project

The upstream project was built entirely with [Claude](https://claude.ai) (Anthropic AI); this fork's changes were also made with Claude and are covered by `tests/` (run `python -m pytest -q`). After development, the following security checks were performed manually:

- **SAST** (Static Application Security Testing) — static analysis of the source code
- **DAST** (Dynamic Application Security Testing) — testing against a running instance
- **Bug check** — manual review of logic and error handling
- **CodeQL** — GitHub's CodeQL analysis workflow, run on the repository

The project is provided as-is. Use it at your own risk and always review the security considerations in the [Hardening](#hardening) section before deploying to production.
