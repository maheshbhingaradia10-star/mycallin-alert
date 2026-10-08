"""GitHub Actions entrypoint; never upload screenshots to public artifacts."""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from mycallin_alert import run, test_email
from render_runner import load_config


def main():
    os.umask(0o077)
    mode = os.environ.get('RUN_MODE', 'scheduled')
    if mode == 'test-email':
        return test_email()
    if mode not in ('scheduled', 'dry-run', 'check-now'):
        raise ValueError('Unknown run mode')
    if mode != 'dry-run' and os.environ.get('ALERTS_ENABLED', 'false').lower() != 'true':
        raise ValueError('Daily alerts are disabled pending live verification')
    # Allow delayed GitHub schedules only within the observed site access hours.
    # The program timezone must still be verified before enabling the schedule.
    now = datetime.now(ZoneInfo('America/Chicago'))
    if not 5 <= now.hour < 18:
        raise ValueError('Outside site access hours; check manually during opening hours')
    cfg = load_config(dry_run=mode == 'dry-run')
    return run(cfg, dry_run=mode == 'dry-run')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as exc:
        print('SETUP ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print('RUN FAILED (' + type(exc).__name__ + '). Check manually.', file=sys.stderr)
        sys.exit(1)
