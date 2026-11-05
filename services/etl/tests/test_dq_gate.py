import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_prices import prepare_prices, save_checked_prices
from run_weather import prepare_weather, save_checked_weather

U = timezone.utc
T = datetime(2026, 11, 1, 0, tzinfo=U)

def price(i, value=10, resolution='PT15M'):
    step = timedelta(minutes=15 if resolution == 'PT15M' else 60)
    t = T + i * step
    return ('FI', t, t + step, resolution, Decimal(value), 'EUR', 'MWH')

def weather(i, temp=10, hum=40):
    return (T + timedelta(hours=i), temp, hum, 20, 4, 100)

class DQGate(unittest.TestCase):
    def test_quarter_hour_gap_up_to_hour_same_mean(self):
        for missing in range(1, 5):
            rows = [price(0, 10), price(missing + 1, 30)]
            saved, events = prepare_prices(rows, 'FI', T, T + timedelta(minutes=15 * (missing + 2)))
            filled = [r for r in saved if r[-1] == 'boundary_mean']
            self.assertEqual(len(filled), missing)
            self.assertEqual({r[4] for r in filled}, {Decimal('20')})
            self.assertEqual(sum(e['reason'] == 'gap_filled_boundary_mean' for e in events), missing)

    def test_hourly_price_gap_exactly_one_hour(self):
        rows = [price(0, 10, 'PT60M'), price(2, 30, 'PT60M')]
        saved, _ = prepare_prices(rows, 'FI', T, T + timedelta(hours=3))
        filled = [r for r in saved if r[-1] == 'boundary_mean']
        self.assertEqual(len(filled), 1)
        self.assertEqual(filled[0][4], Decimal('20'))

    def test_long_gap_and_missing_edges(self):
        rows = [price(1), price(7)]
        saved, events = prepare_prices(rows, 'FI', T, T + timedelta(hours=3))
        self.assertEqual(len(saved), 2)
        self.assertTrue(any(e['reason'] == 'gap_unfilled' for e in events))
        self.assertFalse(any(r[-1] == 'boundary_mean' for r in saved))

    def test_empty_prices_report_whole_range(self):
        rows, events = prepare_prices([], 'FI', T, T + timedelta(days=1))
        self.assertFalse(rows)
        self.assertEqual(events[0]['reason'], 'range_unfilled_no_resolution')

    def test_existing_original_can_bound_gap(self):
        saved, _ = prepare_prices([price(2, 30)], 'FI', T, T + timedelta(minutes=45), [price(0, 10)])
        self.assertEqual(saved[1][4], 20)
        self.assertEqual(saved[1][-1], 'boundary_mean')

    def test_estimate_not_a_boundary(self):
        saved, _ = prepare_prices([price(0), price(6)], 'FI', T, T + timedelta(minutes=105))
        self.assertEqual(len(saved), 2)

    def test_invalid_price_logged_and_replaced(self):
        saved, events = prepare_prices([price(0), price(1, 9999), price(2, 30)], 'FI', T, T + timedelta(minutes=45))
        self.assertEqual(saved[2][-1], 'boundary_mean')
        self.assertTrue(any('price_out_of_range' in e['reason'] for e in events))

    def test_weather_one_hour_and_long_gap(self):
        saved, _ = prepare_weather([weather(0, 10), weather(2, 30)], T, T + timedelta(hours=3))
        estimate = next(r for r in saved if r[-1] == 'boundary_mean')
        self.assertEqual(estimate[1], 20)
        self.assertEqual(estimate[2], 40)
        saved, events = prepare_weather([weather(0), weather(3)], T, T + timedelta(hours=4))
        self.assertEqual(len(saved), 2)
        self.assertEqual(sum(e['reason'] == 'gap_unfilled' for e in events), 2)

    def test_weather_edges_and_empty(self):
        saved, events = prepare_weather([weather(1)], T, T + timedelta(hours=3))
        self.assertEqual(len(saved), 1)
        self.assertEqual(sum(e['reason'] == 'gap_unfilled' for e in events), 2)
        saved, events = prepare_weather([], T, T + timedelta(hours=3))
        self.assertFalse(saved)
        self.assertEqual(sum(e['reason'] == 'gap_unfilled' for e in events), 3)

    def test_database_upsert_prefers_original(self):
        for saver, records, args in (
            (save_checked_prices, [price(0), price(2, 30)], ('FI', T, T + timedelta(minutes=45))),
            (save_checked_weather, [weather(0), weather(2, 30)], ('FI-HELSINKI-01', T, T + timedelta(hours=3))),
        ):
            conn = MagicMock()
            cursor = conn.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = []
            saver(conn, args[0], records, args[1], args[2])
            query = cursor.executemany.call_args_list[-1].args[0]
            values = cursor.executemany.call_args_list[-1].args[1]
            self.assertIn('EXCLUDED.imputation_method IS NULL', query)
            self.assertIn('imputation_method IS NOT NULL', query)
            self.assertTrue(any(row[-1] == 'boundary_mean' for row in values))
            self.assertTrue(any(row[-1] is None for row in values))

if __name__ == '__main__':
    unittest.main()
