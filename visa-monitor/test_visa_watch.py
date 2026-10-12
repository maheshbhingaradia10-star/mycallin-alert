import json
import os
from pathlib import Path
import smtplib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import visa_watch as watch

NOW = datetime(2026, 10, 12, 16, 30, tzinfo=timezone.utc)


def page(**changes):
    slot = {'visa_location': 'HYDERABAD VAC', 'visa_type': 'H-1B (Regular)',
            'createdon': '2026-10-12 16:00:00', 'no_of_dates': 2,
            'no_of_apnts': 0, 'earliest_date': '25 Nov, 26', 'imghash': 'abcDEF0123'}
    slot.update(changes)
    payload = '25:' + json.dumps({'initialData': {'createdon': NOW.timestamp() * 1000, 'slots': [slot]}})
    return '<script>self.__next_f.push(' + json.dumps([1, payload]) + ')</script>'


class ParserTests(unittest.TestCase):
    def test_exact_report_and_utc_conversion(self):
        report, = watch.parse_reports(page(), NOW)
        self.assertEqual(report.appointment.isoformat(), '2026-11-25')
        self.assertEqual(report.reported_at.astimezone(watch.INDIA).strftime('%H:%M %Z'), '21:30 IST')
        self.assertEqual(report.reported_at.astimezone(watch.CHICAGO).strftime('%H:%M %Z'), '11:00 CDT')

    def test_no_false_openings(self):
        cases = [
            {'createdon': '2026-10-12 15:29:59'},
            {'createdon': '2026-10-12 16:31:00'},
            {'createdon': '2026-10-12T16:00:00'},
            {'createdon': '12 Oct 2026 11:00 EST'},
            {'createdon': None},
            {'visa_location': 'HYDERABAD'},
            {'visa_location': 'CHENNAI VAC'},
            {'visa_type': 'H-1B (Interview Waiver)'},
            {'visa_type': 'H-4 (Regular)'},
            {'earliest_date': '12 Oct, 26'},
            {'earliest_date': '01 Jan, 25'},
            {'earliest_date': 'not available'},
            {'no_of_dates': 0},
            {'imghash': None},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(watch.parse_reports(page(**changes), NOW), [])

    def test_unknown_schema_and_stale_snapshot_fail_closed(self):
        for doc in ['<p>H1B Hyderabad VAC available today</p>', page().replace('initialData', 'newSchema')]:
            with self.assertRaises(watch.SourceError):
                watch.parse_reports(doc, NOW)
        with self.assertRaises(watch.SourceError):
            watch.parse_reports(page(), NOW + timedelta(hours=2))

    def test_dedup_independent_of_refreshed_timestamp(self):
        original, = watch.parse_reports(page(), NOW)
        refreshed, = watch.parse_reports(page(createdon='2026-10-12 16:10:00'), NOW)
        self.assertEqual(original.key, refreshed.key)

    def test_chicago_dst_uses_date_specific_offset(self):
        winter = datetime(2026, 11, 10, 16, tzinfo=timezone.utc)
        self.assertEqual(winter.astimezone(watch.CHICAGO).strftime('%H:%M %Z'), '10:00 CST')

    def test_retry_after_is_respected(self):
        self.assertEqual(watch.retry_delay('7200', NOW), 7200)
        self.assertGreaterEqual(watch.retry_delay('Mon, 12 Oct 2026 18:30:00 GMT', NOW), 7200)


class FakeSMTP:
    behavior = 'accept'
    calls = 0
    def __init__(self, *args, **kwargs): pass
    def ehlo(self): pass
    def login(self, *args): pass
    def mail(self, *args): return 250, b'ok'
    def rcpt(self, *args): return 250, b'ok'
    def data(self, *args):
        type(self).calls += 1
        if self.behavior == 'uncertain':
            raise smtplib.SMTPServerDisconnected('disconnect after data')
        if self.behavior == 'reject':
            return 450, b'temporary rejection'
        return 250, b'ok'
    def quit(self): raise smtplib.SMTPServerDisconnected('quit disconnected')
    def close(self): pass


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state.json'
        self.state = watch.load_state(self.path)
        self.env = patch.dict(os.environ, {'SMTP_USERNAME': 'sender@example.com',
                              'SMTP_PASSWORD': 'test-password', 'EMAIL_TO': 'recipient@example.com'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.smtp = patch.object(watch.smtplib, 'SMTP_SSL', FakeSMTP)
        self.smtp.start()
        self.addCleanup(self.smtp.stop)
        FakeSMTP.calls = 0

    def test_acceptance_recorded_after_data_even_if_quit_fails(self):
        FakeSMTP.behavior = 'accept'
        watch.send_message(watch.compose(None, 'key'), 'key', self.state, self.path)
        self.assertEqual(watch.load_state(self.path)['reports']['key']['status'], 'accepted')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_ambiguous_data_never_marked_accepted(self):
        FakeSMTP.behavior = 'uncertain'
        with self.assertRaises(watch.DeliveryUncertain):
            watch.send_message(watch.compose(None, 'key'), 'key', self.state, self.path)
        self.assertEqual(watch.load_state(self.path)['reports']['key']['status'], 'pending')

    def test_definite_rejection_can_retry(self):
        FakeSMTP.behavior = 'reject'
        with self.assertRaises(smtplib.SMTPException):
            watch.send_message(watch.compose(None, 'key'), 'key', self.state, self.path)
        self.assertNotIn('key', watch.load_state(self.path)['reports'])

    def test_existing_pending_report_is_not_resent(self):
        report, = watch.parse_reports(page(), NOW)
        self.state['reports'][report.key] = {'status': 'pending'}
        watch.save_state(self.path, self.state)
        with patch.object(watch, 'fetch_document', return_value=page()), patch.object(watch, 'parse_reports', return_value=[report]):
            watch.check_once(self.path, 120)
        self.assertEqual(FakeSMTP.calls, 0)


if __name__ == '__main__':
    unittest.main()
