# Hyderabad H-1B VAC email watcher

Reads only the public [CheckVisaSlots regular H-1B snapshot](https://checkvisaslots.com/latest-us-visa-availability/h-1b-regular/). It does not access or sign into the visa portal, book anything, or bypass access controls.

An email requires an exact H-1B (Regular), HYDERABAD VAC/OFC report, a future India appointment date, and an unambiguous report timestamp within 60 minutes. The timestamp is interpreted as UTC, as the source's published client does. Emails include the earliest disclosed appointment date, report time in India and Chicago, source link, and a community-report disclaimer. Other dates may exist but are not disclosed by this public snapshot.

## Running service

The `Hyderabad H-1B VAC alerts` GitHub Actions workflow requests a worker every five minutes. A single worker checks every 120 seconds for 24 minutes; concurrency prevents overlapping workers, and the latest pending run takes over afterward. GitHub can delay or drop scheduled starts. This is best-effort polling, not guaranteed continuous monitoring. Public repositories' scheduled workflows can be disabled after 60 days without repository activity. Check Actions for failures or inactivity.

The public source says it updates every two minutes, but its underlying community observations may be much older. A successful check with zero qualifying reports means no qualifying public evidence, not proof that the portal has no appointments.

Delivery uses Gmail TLS and existing encrypted Actions secrets. `VISA_EMAIL_TO` supplies the Gmail sender and destination; `SMTP_PASSWORD` supplies the existing Gmail app password. Credentials and the email address are never committed. Only public report identifiers, deduplication status and retry timestamps are cached. Normal runs retain deduplication through Actions cache; a killed worker or cache eviction can lose unsaved records. An ambiguous SMTP acknowledgement is suppressed when its state survives. SMTP acceptance does not prove inbox delivery.

To stop: Actions → Hyderabad H-1B VAC alerts → Disable workflow. Cancel a running worker too if immediate stopping is required. To resume: Enable workflow and run `monitor` manually.

## Manual workflow modes

- `monitor`: starts a 24-minute polling worker.
- `test-email`: sends one clearly labelled setup test, without an availability claim.
- `check-now`: checks once, sending an email only for a new qualifying report.
- `dry-run`: fetches and validates the public source without sending email.

## Local execution

Python 3.10+ on Linux, no external packages. Provide `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_TO` through private environment configuration.

```sh
python visa-monitor/visa_watch.py --loop --interval 120 --state state/visa-watch.json
python -m unittest discover -s visa-monitor -p 'test_*.py' -v
```

HTTP throttling respects Retry-After; authentication/access errors back off. Unknown formats and uncertain times fail closed. No undocumented API endpoints are used.
