# Investor Room: SMS access release

Prepared 25 November 2026. This release is local; it does not enable authentication on GitHub Pages.

## Hosting decision and public copies

Use the existing ShuddhaSangama repository and a new Railway service for the corporate website and Investor Room. The app continues separately. Serve the whole corporate domain from Railway to preserve `https://shuddhasangama.org/investors/`; DNS cannot route only a URL path. Existing corporate pages are served by the backend too.

The current public GitHub repository/history and previously published assets remain public. Login cannot make those copies private. Keep new confidential material in the encrypted database or uploaded private documents, not in HTML/JS or Git. This release's proposal importer is for precisely that purpose. Public marketing films on dhashu.com remain public. Do not publish confidential source material into this repo.

Disable GitHub Pages before pushing this release if the new funding summaries must not appear publicly. Until DNS cutover, this causes a maintenance window. Alternatively prepare Railway from a private local upload first, then disable Pages and change DNS. Do not claim that the old public room is protected until the cutover and anonymous-access checks below pass.

## 1. Prepare source and create Railway resources

After disabling GitHub Pages for this repository, push the prepared local commit from PowerShell:

```powershell
cd C:\DreamContractLocalBKP\ChatGPT\shuddhasangama-corporate
git status --short
git push origin HEAD:main
```

Do not add the source proposal or secrets to Git. This release keeps the detailed proposal in runtime encrypted storage.


In the existing Railway project, create a NEW service named `shuddhasangama-site` from `shuddhasangama/ShuddhaSangama`, root directory `/`. Do not change Dream-Sim, dhashu-admin or bgv-worker.

Add a NEW dedicated PostgreSQL service for investor records. Do not use the app's database or any older investor database. Attach a persistent volume to the website service at `/data` for private PDF uploads. PostgreSQL stores encrypted investor details and the proposal; the volume stores encrypted PDFs. Configure backups for both and retain the encryption key securely.

The root Dockerfile starts Gunicorn; railway.json runs `python investor_backend/manage.py init-db` before deployment. It creates the dedicated schema without deleting records. Health check: `/health`.

## 2. Variables (website service only)

Generate independent secrets locally:

```powershell
cd C:\DreamContractLocalBKP\ChatGPT\shuddhasangama-corporate
python investor_backend/manage.py keys
```

This prints secrets for you to save directly into Railway, not chat or Git. Use the existing investor Python environment if your default Python lacks dependencies, or install `investor_backend/requirements.txt` into a virtual environment.

Set:

| Variable | Value |
|---|---|
| APP_ENV | production |
| PUBLIC_URL | https://shuddhasangama.org/investors/ |
| DATABASE_URL | Reference the NEW PostgreSQL service connection URL |
| SECRET_KEY | Generated secret |
| LOOKUP_KEY | Generated independent secret |
| DATA_ENCRYPTION_KEY | Generated Fernet key; retain it for recovery |
| PRIVATE_STORAGE | /data/documents |
| TWILIO_ACCOUNT_SID | Account owning the Verify service (non-India numbers) |
| TWILIO_AUTH_TOKEN | Its secret token |
| TWILIO_VERIFY_SERVICE_SID | A Twilio Verify service with the SMS channel on and 6-digit codes. Use a service made for the Investor Room, not the app's `DhaShu` service. |
| MSG91_AUTH_KEY | A NEW MSG91 Authkey named `investorRoom` with IP security off (India numbers). Do not reuse `dhashuBackend`; it is limited to fixed IPs. |
| MSG91_TEMPLATE_ID | An approved OTP template ID, for example the DLT-verified `DhaShuSignup` template |
| MSG91_COUNTRY_CODES | Optional. Country codes sent through MSG91, comma separated. Default `91`. Use `91,1` later to move US/Canada to MSG91. |
| INVESTOR_SESSION_HOURS | Optional. Hours an investor stays signed in. Default 8, allowed 1 to 72. Admin sessions stay 1 hour. |

Do not enable public-preview. No email provider or SendGrid account is needed: sign-in codes go by SMS only. Configure Verify and the MSG91 template for six-digit codes. Local challenges expire after five minutes, allow five checks, and resend is limited to once per minute/eight per day per mobile number. IP limits additionally apply. Only configure TRUST_PROXY=1 if exactly one trusted proxy supplies the client address and direct spoofed forwarding headers are prevented; leave unset otherwise (shared-IP throttling may be more restrictive).

## 3. SMS providers (MSG91 and Twilio Verify)

The mobile number's country code decides the provider. Numbers starting +91 use MSG91 SendOTP. Every other number (US, Canada, UAE, Europe) uses Twilio Verify SMS. To move more countries to MSG91 later, change `MSG91_COUNTRY_CODES` only; no code change is needed.

MSG91: in Settings > Authkey create a separate key named `investorRoom` with IP security off. Keep the existing `dhashuBackend` key untouched. Use an OTP template that is verified by DLT (OTP > Templates), and put its ID in `MSG91_TEMPLATE_ID`. The code is generated and checked by MSG91.

Twilio: in Verify > Services create `Investor Room SMS` with the SMS channel on and 6-digit codes. Check Verify > Fraud & Geo Permissions allows the countries your investors are in. The old `Investor Room Email` service is no longer used.

The application requires the provider's approved result. For Twilio it must match the exact verification SID. A send acceptance alone does not grant access. No SMS is sent by deployment or by adding an investor.

Before sharing the link, test one real number in each region you have investors: India, US, UAE and one European country. Roaming and eSIM users may not receive Indian SMS abroad; if that happens, replace the number in the admin directory for the trip.

## 4. Initialise your admin and private proposal

After deployment, open the NEW website service's Railway console:

```sh
cd /app
python investor_backend/manage.py admin
```

Follow the prompts for a password (12+ characters) and a new authenticator entry. This is a separate founder login from the existing app admin; credentials are not automatically shared.

Open `/admin/login`. Add approved investors with name, login mobile number including country code (for example +91 or +1), email for contact only, current company, base city and access duration. The mobile number and email are both required and each must be unique. Investors sign in with the mobile number. Approval verifies your permission to enter; the SMS code verifies control of the number. Changing an investor's number in the directory moves their login to the new number and cancels any pending code. Revoke or renew access in the same directory.

The Ask section links to `/room/ask`, which is private server-rendered content. Paste the approved proposal into the admin's Investment ask content editor; it is encrypted in the database. Or securely transfer the original HTML to the Railway service's temporary directory and run:

```sh
python investor_backend/import_proposal.py /tmp/proposal.html
```

Do not commit that HTML. The importer adds a note about the older rollout in the source proposal and the cap table's ₹50 lakh assumption. The proposal's ₹60 lakh cap needs revised holdings before any final terms are issued. The private PDF upload is also available in admin.

## 5. Connect the existing domain

Generate a Railway temporary domain and verify the login/admin/public corporate pages first. Add `shuddhasangama.org` as a custom domain in Railway and follow Railway's exact DNS records at the current DNS provider. Preserve mail/MX/TXT records for company email. Disable the old GitHub Pages site so its alternate URL cannot bypass the gate. If www is used, configure it too.

No Codemagic build, app-user deletion, app-database changes or app OTP switch is needed.

## 6. Release acceptance checks

- Signed out: `/investors/`, `/investors/assets/room.js`, and `/investors/assets/DhaShu-financial-plan.xlsx` redirect to login. No private page content appears in the response.
- Unapproved number: generic response, no SMS sent and no access.
- Approved +91 number: receive the MSG91 SMS, verify, acknowledge access terms, enter the room.
- Approved US, UAE and European numbers: receive the Twilio SMS and enter the room.
- Typing an email address on the login page does not sign anyone in.
- Wrong/expired/reused code fails; repeated sends are throttled.
- Founder: open admin, add/edit contact details, preview room, renew/revoke access.
- Revoke an investor while logged in: their next room/download request is denied.
- Check Ask, Use of funds, benchmark accordion, roadmap, videos and Excel download.
- Confirm the old GitHub Pages URL is disabled. Previously downloaded or public Git copies cannot be recalled.

Local automated tests use fake providers, not real SMS. Live SMS delivery in each country, production PostgreSQL concurrency, DNS and SSL must be verified in the deployed environment before sharing the protected link.
