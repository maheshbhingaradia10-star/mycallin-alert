# MyCallIn daily email alert

Checks MyCallIn, captures its result card, and emails a PNG attachment with
`TEST REQUIRED TODAY`, `NO TEST TODAY`, or `STATUS UNKNOWN` in the subject.
**Not live or fully configured.** The site adapter still needs verification.
Personal credentials, email addresses, IDs, tokens, and screenshots must stay
out of this public repository. Store real values in Render Environment settings.

## Email sender setup

This version uses Gmail SMTP over verified TLS, replacing WhatsApp entirely.
It needs no Meta account, WhatsApp sender, or message template.

1. Choose a Gmail account you own to send the alerts. It can also receive them.
2. Enable Google 2-Step Verification, then create an app password named
   `MyCallIn Alerts` at https://myaccount.google.com/apppasswords . Some account
   policies do not permit app passwords; do not use your normal Gmail password.
3. Enter the following privately in the Render deployment form or Environment:
   - `SMTP_USERNAME`: full sending Gmail address.
   - `SMTP_PASSWORD`: the 16-character app password (spaces are removed).
   - `EMAIL_TO`: the single receiving email address.
4. Run `python render_runner.py --test-email` in a manual Render shell to send
   a clearly labelled test image. This deliberately works with alerts disabled
   and does not open MyCallIn. Check both inbox and spam for receipt.

SMTP acceptance does not guarantee delivery. Credentials can be revoked;
changing your Google password also revokes app passwords. Do not paste passwords
into chat, screenshots, logs, or GitHub. A Gmail connection inside ChatGPT does
not by itself provide credentials to the unattended Python process on Render.

## Render deployment

The repository includes `render.yaml` for a Docker cron service. Start setup:
https://dashboard.render.com/select-repo?type=blueprint

Select this repository and review the Blueprint. The only initial private form
fields are the sender address, app password, and destination address.
`ALERTS_ENABLED=false` is the default. A disabled run performs no site check and
sends no email. **Do not treat a successful build as a working daily alert.**
Render cron services have a $1 monthly minimum; review displayed charges before
creating the service. No paid resource is created merely by committing this file.

Manual alternative: New Cron Job, this repository's `main` branch, Docker,
`./Dockerfile`, command `python render_runner.py`, schedule `5 10,11 * * *`.

## Site verification still required

The observed site notice allows check-in from 5 a.m. to 6 p.m., without stating
a timezone. Confirm the program uses America/Chicago before enabling this
proposed 5:05 a.m. schedule. The remaining login steps and result page have not
yet been inspected. Never guess selectors or result phrases.

During the site's permitted hours, inspect the authorized login flow and fill
`site_config.example.json` with the exact observed selectors, today's date format
(including a four-digit year), and distinct complete yes/no status phrases.
Scope `result_selector` narrowly to the result card; it must not contain login
inputs or unrelated records. `status_selector` and `date_selector` are relative
to that card. Only add verified continuation buttons, without automatically
accepting agreements or bypassing verification challenges.

Then configure these private Render variables:

| Variable | Purpose |
|---|---|
| `MYCALLIN_PHONE` | Program's drug-testing phone number |
| `MYCALLIN_LAST_NAME` | Account last name |
| `MYCALLIN_ID` | Account ID |
| `MYCALLIN_CONFIG_JSON` | Verified JSON configuration |
| `ALERTS_ENABLED` | Keep `false` until validation is complete |

Validate with `python render_runner.py --check-setup --dry-run`. For a live site
check without email, explicitly set `ALERTS_ENABLED=true` for the command and run
`python render_runner.py --now --dry-run`. Review the result screenshot privately
and confirm classification before enabling scheduled runs. For a full manual
check and email, use `--now` without `--dry-run` after setup is verified.

## Scheduling and failure behavior

Render uses UTC. The cron expression starts at 10:05 and 11:05 UTC; the script
only checks during 05:05-05:20 America/Chicago, so exactly one candidate is
eligible in either standard or daylight time. Delays beyond this window are
skipped and require manual checking. The cloud job can run while your PC is off.

Unknown wording, stale dates, ambiguity, closed pages, and login/network failures
never become `NO TEST TODAY`. Failed checks email an explicit unknown status
with a labelled failure image; they exit nonzero. Invalid configuration or mail
failures also exit nonzero, but cannot guarantee an email is sent. The screenshot
is attached only after the configured result card is found.

Render cron files are ephemeral: the local duplicate record is best effort,
not durable across runs/deploys. There are no automatic send retries because
SMTP timeouts can have ambiguous delivery outcomes. Manual re-runs may duplicate
an email. Configure Render failure notifications and maintain a separate manual
check until end-to-end execution and delivery have been verified.

## Local verification

`python -m unittest discover -s tests -v`

Tests cover status negation, date freshness, ambiguous status, DST scheduling,
disabled behavior, email attachment content, and rejecting malformed addresses.
Live site access, Docker build, SMTP authentication, and inbox delivery remain
unverified. Setup tests never claim to be a real test result.
