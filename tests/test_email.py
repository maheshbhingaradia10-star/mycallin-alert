import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mycallin_alert import UNKNOWN, build_email, email_settings, send


class EmailTests(unittest.TestCase):
    def test_email_status_and_attachment(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'test.png'
            content = b'\x89PNG\r\n\x1a\nfixture'
            path.write_bytes(content)
            for status in ('TEST REQUIRED TODAY', 'NO TEST TODAY', UNKNOWN):
                with self.subTest(status=status):
                    msg = build_email(path, datetime.fromisoformat('2026-10-08T05:05:00-05:00'),
                                      status, 'sender@example.com', 'recipient@example.com')
                    self.assertIn(status, msg['Subject'])
                    self.assertIn(status, msg.get_body().get_content())
                    attachments = list(msg.iter_attachments())
                    self.assertEqual(len(attachments), 1)
                    self.assertEqual(attachments[0].get_content_type(), 'image/png')
                    self.assertEqual(attachments[0].get_content(), content)
                    if status == UNKNOWN:
                        self.assertIn('could not be confirmed', msg.get_body().get_content())

    def test_reject_multiple_recipients_and_header_injection(self):
        for recipient in ('a@example.com,b@example.com', 'a@example.com\nBcc: b@example.com'):
            with self.subTest(recipient=recipient), patch.dict(os.environ, {
                'SMTP_USERNAME': 'sender@example.com', 'SMTP_PASSWORD': 'abcdefghijklmnop',
                'EMAIL_TO': recipient,
            }, clear=True):
                with self.assertRaises(ValueError):
                    email_settings()

    def test_sender_uses_tls_and_explicit_recipient(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'test.png'
            path.write_bytes(b'fixture')
            with patch.dict(os.environ, {
                'SMTP_USERNAME': 'sender@example.com', 'SMTP_PASSWORD': 'abcd efgh ijkl mnop',
                'EMAIL_TO': 'recipient@example.com',
            }, clear=True), patch('mycallin_alert.smtplib.SMTP_SSL') as smtp:
                connection = smtp.return_value.__enter__.return_value
                connection.send_message.return_value = {}
                send({}, path, datetime.fromisoformat('2026-10-08T05:05:00-05:00'), UNKNOWN, test=True)
                self.assertEqual(smtp.call_args.args, ('smtp.gmail.com', 465))
                self.assertTrue(smtp.call_args.kwargs['context'].check_hostname)
                connection.login.assert_called_once_with('sender@example.com', 'abcdefghijklmnop')
                call = connection.send_message.call_args
                self.assertEqual(call.kwargs['to_addrs'], ['recipient@example.com'])
                self.assertIn('no website check performed', call.args[0]['Subject'])
                self.assertNotIn('NO TEST TODAY', call.args[0]['Subject'])
