import os
import unittest
from unittest.mock import patch

from github_runner import main


class GitHubRunnerTests(unittest.TestCase):
    def test_disabled_schedule_never_checks_or_sends(self):
        with patch.dict(os.environ, {'RUN_MODE': 'scheduled', 'ALERTS_ENABLED': 'false'}, clear=True), \
                patch('github_runner.run') as run:
            with self.assertRaises(ValueError):
                main()
            run.assert_not_called()

    def test_setup_email_never_checks_website(self):
        with patch.dict(os.environ, {'RUN_MODE': 'test-email'}, clear=True), \
                patch('github_runner.test_email', return_value=0) as email, \
                patch('github_runner.run') as run:
            self.assertEqual(main(), 0)
            email.assert_called_once_with()
            run.assert_not_called()
