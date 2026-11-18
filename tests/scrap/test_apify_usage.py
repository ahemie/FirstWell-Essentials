import os
import unittest
from unittest import mock

os.environ.setdefault('FLASK_SECRET_KEY', 'k' * 40)
from backend import scrap_api as app


class ApifyUsageTests(unittest.TestCase):
    def test_parse_limits(self):
        payload = {'data': {'monthlyUsageCycle': {'startAt': '2026-11-01T00:00:00Z', 'endAt': '2026-11-30T23:59:59Z'},
                            'limits': {'maxMonthlyUsageUsd': 5}, 'current': {'monthlyUsageUsd': 1.2345}}}
        got = app.parse_apify_limits(payload)
        self.assertEqual(got, {'used_usd': 1.2345, 'limit_usd': 5.0, 'remaining_usd': 3.7655, 'cycle_ends': '2026-11-30T23:59:59Z'})

    def test_remaining_never_negative(self):
        got = app.parse_apify_limits({'data': {'limits': {'maxMonthlyUsageUsd': 5}, 'current': {'monthlyUsageUsd': 5.4}}})
        self.assertEqual(got['remaining_usd'], 0)

    def test_bad_shape(self):
        for bad in [{}, {'data': {}}, None, {'data': {'limits': {}, 'current': {}}}]:
            with self.assertRaises(ValueError):
                app.parse_apify_limits(bad)

    def test_run_cost(self):
        self.assertEqual(app.run_cost_usd({'usageTotalUsd': 0.01234}), 0.0123)
        self.assertEqual(app.run_cost_usd({'usage_total_usd': '0.2'}), 0.2)
        self.assertIsNone(app.run_cost_usd({}))
        self.assertIsNone(app.run_cost_usd(None))
        self.assertIsNone(app.run_cost_usd({'usageTotalUsd': 'abc'}))

    def test_money_text(self):
        self.assertEqual(app.money_usd(None), 'unknown')
        self.assertEqual(app.money_usd(0.0043), '$0.004')
        self.assertEqual(app.money_usd(0.0123), '$0.012')
        self.assertEqual(app.money_usd(3.7655), '$3.77')
        self.assertEqual(app.money_usd(0), '$0.00')

    def test_no_token_means_not_configured_and_no_network(self):
        with mock.patch.dict(os.environ, {'APIFY_TOKEN': ''}), mock.patch('urllib.request.urlopen') as net:
            self.assertIsNone(app.apify_usage())
            net.assert_not_called()

    def test_network_failure_is_swallowed(self):
        with mock.patch.dict(os.environ, {'APIFY_TOKEN': 'x'}), mock.patch('urllib.request.urlopen', side_effect=OSError('down')):
            self.assertIsNone(app.apify_usage())


if __name__ == '__main__':
    unittest.main()
