import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

from mycallin_alert import UNKNOWN, classify
from render_runner import in_window, main


class SafetyTests(unittest.TestCase):
    def test_negation_and_freshness(self):
        cfg = {"date_format": "%m/%d/%Y", "yes_phrases": ["You must test today."],
               "no_phrases": ["You do not test today."]}
        cases = [
            ("You must test today.", "10/07/2026", "TEST REQUIRED TODAY"),
            ("You do not test today.", "10/07/2026", "NO TEST TODAY"),
            ("You do not test today.", "10/06/2026", UNKNOWN),
            ("You do not test today.", "invalid", UNKNOWN),
            ("You do not test today. You must test today.", "10/07/2026", UNKNOWN),
            ("You are checking in too late", "10/07/2026", UNKNOWN),
        ]
        for text, day, expected in cases:
            with self.subTest(text=text, day=day):
                self.assertEqual(classify(text, day, cfg, date(2026, 10, 7)), expected)

    def test_exactly_one_eligible_utc_candidate(self):
        # Ordinary dates and both U.S. daylight-saving transition dates.
        for day in ("2026-01-10", "2026-07-10", "2026-03-08", "2026-11-01"):
            with self.subTest(day=day):
                candidates = [datetime.fromisoformat(day + "T" + hour + ":05:00+00:00")
                              for hour in ("10", "11")]
                self.assertEqual(sum(in_window(t) for t in candidates), 1)

    def test_disabled_does_not_call_site_or_sender(self):
        with patch.dict(os.environ, {"ALERTS_ENABLED": "false"}), \
                patch("sys.argv", ["render_runner.py"]), \
                patch("render_runner.run") as run:
            self.assertEqual(main(), 0)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
