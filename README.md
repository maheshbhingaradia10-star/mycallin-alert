# MyCallIn daily alert

Cloud deployment scaffold for a daily MyCallIn check, a result-card screenshot,
and an explicit WhatsApp notification. **Not live or fully configured.**
No credentials, phone numbers, names, IDs, tokens, or personal screenshots belong
in this repository. Add real values only in Render's Environment settings.

## Current state

- Status/date classification and daylight-saving schedule logic tested locally.
- Login and result selectors are intentionally blank, not guessed.
- MyCallIn's remaining steps and result wording have not been inspected.
- Docker build, live site access, and WhatsApp delivery have not been tested.
- Hosting and a Meta WhatsApp Business sender have not been activated.

The observed site notice permits check-in from 5 a.m. to 6 p.m. It does not
specify a timezone. This package proposes 5:05 a.m. America/Chicago; confirm that
the program uses Central Time before enabling it. No result is inferred from a
closed page, network failure, sign-in failure, or yesterday's date.

## Upload and create the Render service

1. Upload the extracted project files to the GitHub repository root. Upload the
   files themselves, not the ZIP or a containing directory. Include dotfiles.
2. In Render choose **New Cron Job > Git Provider**, select this repository and
   branch `main`. Use the repository's **Docker** runtime and `./Dockerfile`.
3. Name: `mycallin-alert`. Schedule: `5 10,11 * * *`. Docker Command:
   `python render_runner.py` (also the image default). No separate build command.
4. Set `ALERTS_ENABLED=false` initially. Review Render's displayed charges before
   deploying. Render documents a $1 minimum monthly charge per cron service;
   actual runtime and WhatsApp charges may add to that.
5. A build with alerts disabled only verifies deployment. The log will say
   `DISABLED`; it has NOT checked MyCallIn or sent WhatsApp.

Render schedules use UTC. This schedule starts at both 10:05 and 11:05 UTC.
The Python entrypoint only runs the website check during 05:05-05:20 Central,
so the other invocation exits. This accommodates daylight saving without editing
the cron expression. A delay beyond the window is skipped, not reported as a
successful website check. Inspect Render Runs and maintain an independent
reminder until execution and delivery monitoring are in place.

## Environment variables

| Name | Value to enter privately |
|---|---|
| `ALERTS_ENABLED` | `false` until validation is complete; then `true` |
| `MYCALLIN_PHONE` | Program's Drug Testing Phone Number |
| `MYCALLIN_LAST_NAME` | Account last name |
| `MYCALLIN_ID` | Account ID |
| `MYCALLIN_CONFIG_JSON` | Completed contents of `site_config.example.json` |
| `WA_ACCESS_TOKEN` | Meta token authorized for the WhatsApp sender |
| `WA_PHONE_NUMBER_ID` | Meta sender phone-number ID, not your receiving number |
| `WA_API_VERSION` | Supported Graph API version selected in the Meta app |
| `WA_TO` | Your receiving WhatsApp number with country code, digits only |

Use Meta's WhatsApp Business Cloud API. A personal WhatsApp number alone is not
an API sender. A Twilio account would require a different sending implementation.
Never paste access tokens into chat, repository files, logs, or screenshots.

## Finish the site adapter during access hours

Inspect the real page with Playwright Inspector or developer tools. Fill in CSS
selectors for the three login fields and Next button. Add only verified
continuation buttons to `continuation_selectors`; do not guess later steps,
auto-accept agreements, or bypass verification challenges.

`result_selector` must identify just the current result card. `status_selector`
and `date_selector` are relative to that card. The card must not contain login
fields or unrelated history. `date_format` must parse the entire displayed date
and include `%Y`. If the website does not expose a date, adapt and validate this
logic before enabling it; do not remove freshness checks just to get a result.
Enter exact observed complete sentences in `yes_phrases` and `no_phrases`.
Both cases need verification. Set `verified=true` only after this is complete.

TLS certificate errors must be fixed at their source. Verification remains on.
The current adapter only handles form fields and verified continuation clicks;
if later steps need other actions, code changes will be necessary.

## Configure WhatsApp

Provision a Meta WhatsApp Business sender and authorize the receiving number.
Create an approved template named `mycallin_daily`, language `en_US`, with an
IMAGE header and exactly three numbered body variables. Suggested body:

> MyCallIn check for {{1}}: {{2}}. Checked at {{3}}. Review the attached image.
> If status is unknown, check MyCallIn manually.

Submit synthetic example data, not personal records, for approval. Approval is
subject to Meta's requirements and is not guaranteed. Daily unattended messages
outside the customer-service window require an approved template. The script
uploads the image directly to Meta and sends the template using its media ID.

Results are `TEST REQUIRED TODAY`, `NO TEST TODAY`, or
`STATUS UNKNOWN - check MyCallIn manually`. If no result screenshot is possible,
the attachment is an explicitly labeled failure notice, not a site screenshot.

## Validate before enabling daily alerts

Run these checks locally with Python 3.11+:

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
python render_runner.py --check-setup
```

After securely configuring the variables and setting `ALERTS_ENABLED=true`,
use `python render_runner.py --now --dry-run` during site access hours. Inspect
the image locally. Then use `python render_runner.py --now` for one live send
and verify the image and text on the receiving phone. `--now` bypasses only this
script's time gate, never the website's restrictions.

API acceptance is not delivery. Add Meta delivery-status webhooks/monitoring
before relying on this unattended. A broken WhatsApp sender cannot deliver its
own failure warning. Failed runs exit nonzero; unknown site status exits 2 even
if its warning is accepted by WhatsApp. Render run logs omit personal status.

Render cron disks are ephemeral. Local duplicate suppression only works while
the state file survives; manual reruns, platform restarts, or retries can send
duplicates. The default schedule makes one eligible attempt daily. There are no
automatic send retries after ambiguous network failures. Do not configure
automatic retries without durable deduplication and delivery tracking.

## Sources

- https://render.com/docs/cronjobs
- https://playwright.dev/python/docs/docker
- https://playwright.dev/python/docs/screenshots
- https://www.twilio.com/docs/whatsapp/key-concepts
- https://www.postman.com/meta/whatsapp-business-platform/folder/13382743-ecb27be5-4d27-4763-bbee-6a8002c04bf3
- https://www.postman.com/meta/whatsapp-business-platform/request/lwtlz1k/send-message-template-interactive
