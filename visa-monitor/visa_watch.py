#!/usr/bin/env python3
"""Read a public, crowdsourced CheckVisaSlots snapshot and email exact matches.

No visa-portal access or credentials. No third-party packages. createdon in the
provider's slot objects is UTC: its published SlotAvailabilityTable client uses
dayjs.utc(s.createdon, 'YYYY-MM-DD HH:mm:ss'). The HTML display's timezone labels
are inconsistent, so this program never parses those labels or relative times.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email import policy
from email.utils import format_datetime, parsedate_to_datetime, parseaddr
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path
import re
import smtplib
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

SOURCE = 'https://checkvisaslots.com/latest-us-visa-availability/h-1b-regular/'
UTC = timezone.utc
INDIA = ZoneInfo('Asia/Kolkata')
CHICAGO = ZoneInfo('America/Chicago')
MAX_AGE = timedelta(minutes=60)
MIN_INTERVAL = 120
LOG = logging.getLogger('visa_watch')


class SourceError(Exception):
    pass


class DeliveryUncertain(Exception):
    """SMTP DATA may have been accepted; automatic retries are suppressed."""


@dataclass(frozen=True)
class Report:
    appointment: date
    reported_at: datetime
    image_hash: str
    dates_count: int

    @property
    def key(self):
        # Same screenshot is not re-alerted if the snapshot timestamp changes.
        raw = f'{SOURCE}|HYDERABAD VAC|H-1B (Regular)|{self.image_hash}|{self.appointment}'
        return hashlib.sha256(raw.encode()).hexdigest()


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.inside = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.items.append(data)


def parse_reports(document: str, now: datetime) -> list[Report]:
    """Fail closed unless the expected public Next.js snapshot schema is present."""
    if now.tzinfo is None:
        raise ValueError('now must include timezone')
    now = now.astimezone(UTC)
    parser = Scripts()
    parser.feed(document)
    decoder = json.JSONDecoder()
    datasets = []
    for script in parser.items:
        for match in re.finditer(r'self\.__next_f\.push\(', script):
            try:
                push, _ = decoder.raw_decode(script[match.end():])
            except (ValueError, TypeError):
                continue
            if not isinstance(push, list) or len(push) != 2 or not isinstance(push[1], str):
                continue
            payload = push[1]
            for start in re.finditer(r'"initialData"\s*:\s*', payload):
                try:
                    data, _ = decoder.raw_decode(payload[start.end():])
                except (ValueError, TypeError):
                    continue
                if isinstance(data, dict) and isinstance(data.get('slots'), list):
                    datasets.append(data)
    if len(datasets) != 1:
        raise SourceError('expected exactly one public availability dataset')
    data = datasets[0]
    generated = data.get('createdon')
    if type(generated) not in (int, float) or not 1_000_000_000_000 < generated < 9_999_999_999_999:
        raise SourceError('snapshot timestamp missing or unknown format')
    generated_at = datetime.fromtimestamp(generated / 1000, UTC)
    if not -timedelta(minutes=2) <= now - generated_at <= MAX_AGE:
        raise SourceError('snapshot is stale or timestamp is in the future')

    found = {}
    for slot in data['slots']:
        if not isinstance(slot, dict):
            continue
        if slot.get('visa_location') not in ('HYDERABAD VAC', 'HYDERABAD OFC'):
            continue
        if slot.get('visa_type') != 'H-1B (Regular)':
            continue
        stamp = slot.get('createdon')
        earliest = slot.get('earliest_date')
        identity = slot.get('imghash')
        count = slot.get('no_of_dates')
        if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', stamp):
            continue
        if not isinstance(earliest, str) or not re.fullmatch(r'\d{2} [A-Z][a-z]{2}, \d{2}', earliest):
            continue
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,128}', identity):
            continue
        if type(count) is not int or count <= 0:
            continue
        try:
            reported = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
            appointment = datetime.strptime(earliest, '%d %b, %y').date()
        except ValueError:
            continue
        # Future-dated observations are not credible. Only future India dates.
        if not timedelta(0) <= now - reported <= MAX_AGE:
            continue
        if reported > generated_at + timedelta(seconds=1):
            continue
        if appointment <= now.astimezone(INDIA).date():
            continue
        report = Report(appointment, reported, identity, count)
        found[report.key] = report
    return sorted(found.values(), key=lambda item: item.reported_at)


def load_state(path: Path):
    if not path.exists():
        return {'version': 1, 'reports': {}, 'next_fetch_at': 0}
    state = json.loads(path.read_text())
    if state.get('version') != 1 or not isinstance(state.get('reports'), dict):
        raise ValueError('invalid state; refusing to lose deduplication records')
    return state


def save_state(path: Path, state):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(state, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def state_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def retry_delay(value, now):
    if not value:
        return 300
    try:
        return max(MIN_INTERVAL, int(value))
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return 300
            return max(MIN_INTERVAL, int((parsed - now).total_seconds()) + 1)
        except (TypeError, ValueError, OverflowError):
            return 300


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SourceError('unexpected source redirect')


def fetch_document(state, state_path, now, interval):
    if now.timestamp() < state.get('next_fetch_at', 0):
        return None
    request = urllib.request.Request(SOURCE, headers={
        'User-Agent': 'VisaAvailabilityMonitor/1.0 (personal public-report reader)',
        'Accept': 'text/html',
    })
    state['next_fetch_at'] = now.timestamp() + interval
    save_state(state_path, state)
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=25) as response:
            if response.status != 200 or 'text/html' not in response.headers.get('Content-Type', ''):
                raise SourceError('unexpected source response')
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise SourceError('response too large')
            return raw.decode('utf-8', errors='strict')
    except urllib.error.HTTPError as error:
        if error.code in (429, 503):
            delay = retry_delay(error.headers.get('Retry-After'), now)
            state['next_fetch_at'] = now.timestamp() + max(interval, delay)
        elif error.code in (401, 403):
            state['next_fetch_at'] = now.timestamp() + 3600
        save_state(state_path, state)
        # Never log arbitrary provider bodies/URLs or SMTP exception text.
        raise SourceError(f'HTTP status {error.code}') from None


def email_config():
    user = os.environ.get('SMTP_USERNAME', '').strip()
    password = os.environ.get('SMTP_PASSWORD', '').replace(' ', '').strip()
    recipient = os.environ.get('EMAIL_TO', '').strip()
    for address in (user, recipient):
        if '\r' in address or '\n' in address or parseaddr(address)[1] != address or '@' not in address:
            raise ValueError('SMTP_USERNAME and EMAIL_TO must be individual email addresses')
    if not password:
        raise ValueError('SMTP_PASSWORD is required')
    return user, password, recipient


def compose(report: Report | None, key: str):
    user, _, recipient = email_config()
    msg = EmailMessage()
    msg['From'] = user
    msg['To'] = recipient
    msg['Date'] = format_datetime(datetime.now(UTC))
    msg['Message-ID'] = f'<visa-watch-{key}@{user.split("@", 1)[1]}>'
    if report is None:
        msg['Subject'] = 'SETUP TEST — Hyderabad H-1B VAC email alerts'
        msg.set_content('This is an email setup test, not an appointment availability alert.\n'
                        'The monitor reads public community reports for H-1B regular Hyderabad VAC/OFC.\n'
                        'It does not log into your visa account or book appointments.\n')
    else:
        msg['Subject'] = f'Community report: Hyderabad H-1B VAC — {report.appointment:%d %b %Y}'
        msg.set_content(
            'A public community report matches H-1B (Regular), Hyderabad VAC/OFC.\n\n'
            f'Earliest appointment date reported: {report.appointment:%d %B %Y}\n'
            f'Total dates reported: {report.dates_count} (other dates not exposed by this snapshot)\n'
            f'Report time in India: {report.reported_at.astimezone(INDIA):%d %b %Y %I:%M:%S %p %Z}\n'
            f'Report time in Chicago: {report.reported_at.astimezone(CHICAGO):%d %b %Y %I:%M:%S %p %Z}\n'
            f'Source: {SOURCE}\n\n'
            'This is community-reported availability. Verify it in your own visa portal; '
            'availability has not been independently verified and no appointment has been booked.\n'
        )
    return msg


def send_message(msg, key, state, state_path):
    user, password, recipient = email_config()
    # SMTP debug logging is deliberately never enabled.
    smtp = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30, context=ssl.create_default_context())
    try:
        smtp.ehlo()
        smtp.login(user, password)
        code, _ = smtp.mail(user)
        if code != 250:
            raise smtplib.SMTPException('sender rejected')
        code, _ = smtp.rcpt(recipient)
        if code not in (250, 251):
            raise smtplib.SMTPException('recipient rejected')
        # Durable pending marker precedes DATA: a crash must not create duplicates.
        state['reports'][key] = {'status': 'pending', 'started_at': datetime.now(UTC).isoformat()}
        save_state(state_path, state)
        try:
            code, _ = smtp.data(msg.as_bytes(policy=policy.SMTP))
        except smtplib.SMTPDataError:
            # A definite refusal to begin DATA cannot have delivered the message.
            del state['reports'][key]
            save_state(state_path, state)
            raise
        except Exception:
            raise DeliveryUncertain('SMTP acknowledgement unknown; automatic retry suppressed') from None
        if code != 250:
            del state['reports'][key]
            save_state(state_path, state)
            raise smtplib.SMTPException('message rejected')
        state['reports'][key] = {'status': 'accepted', 'accepted_at': datetime.now(UTC).isoformat()}
        save_state(state_path, state)
        LOG.info('SMTP accepted message key=%s; inbox delivery is unverified', key[:12])
    finally:
        # QUIT errors must never change an already confirmed DATA result.
        try:
            smtp.quit()
        except Exception:
            smtp.close()


def check_once(state_path: Path, interval: int, dry_run=False):
    with state_lock(state_path):
        state = load_state(state_path)
        now = datetime.now(UTC)
        document = fetch_document(state, state_path, now, interval)
        if document is None:
            LOG.info('source backoff active; next request at %s',
                     datetime.fromtimestamp(state['next_fetch_at'], UTC).isoformat())
            return
        reports = parse_reports(document, datetime.now(UTC))
        LOG.info('public source checked; qualifying reports=%d', len(reports))
        if dry_run:
            LOG.info('dry run: no email attempted')
            return
        for report in reports:
            existing = state['reports'].get(report.key)
            if existing:
                if existing.get('status') == 'pending':
                    LOG.warning('SMTP acknowledgement previously unknown; key=%s suppressed', report.key[:12])
                continue
            send_message(compose(report, report.key), report.key, state, state_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--once', action='store_true')
    modes.add_argument('--loop', action='store_true')
    modes.add_argument('--test-email', action='store_true')
    parser.add_argument('--interval', type=int, default=120, help='seconds; minimum 120 (source publishes every 2 minutes)')
    parser.add_argument('--state', type=Path, default=Path('state/visa-watch.json'))
    parser.add_argument('--duration', type=int, default=0, help='stop looping after this many seconds; 0 runs until stopped')
    parser.add_argument('--dry-run', action='store_true', help='fetch and validate source without sending email')
    args = parser.parse_args()
    if args.interval < MIN_INTERVAL:
        parser.error('minimum interval is 120 seconds')
    if args.duration < 0:
        parser.error('duration must not be negative')
    if args.test_email and args.dry_run:
        parser.error('--test-email and --dry-run cannot be combined')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.test_email:
        try:
            with state_lock(args.state):
                state = load_state(args.state)
                key = 'setup-' + hashlib.sha256(os.urandom(32)).hexdigest()
                send_message(compose(None, key), key, state, args.state)
            return 0
        except Exception as error:
            LOG.error('setup email failed (%s); delivery not confirmed', type(error).__name__)
            return 1
    deadline = time.monotonic() + args.duration if args.duration else None
    while True:
        try:
            check_once(args.state, args.interval, args.dry_run)
        except Exception as error:
            if isinstance(error, SourceError):
                # SourceError contains only our fixed diagnostic strings/status codes.
                LOG.error('source check failed: %s; no availability claim made', error)
            else:
                LOG.error('check failed (%s); no availability claim made', type(error).__name__)
            if not args.loop:
                return 1
        if not args.loop:
            return 0
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 0
            time.sleep(min(args.interval, remaining))
            if time.monotonic() >= deadline:
                return 0
        else:
            time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
