"""Real PostgreSQL integration checks. Use a disposable DB via DQ_TEST_DSN."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
from run_prices import save_checked_prices
from run_weather import save_checked_weather

@unittest.skipUnless(os.getenv("DQ_TEST_DSN"), "Set DQ_TEST_DSN to a test PostgreSQL database")
class PostgreSQLDQ(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ["DQ_TEST_DSN"], autocommit=True)
        self.addCleanup(self.conn.close)
        self.schema = "dq_test_" + uuid4().hex
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
        source = Path(__file__).resolve().parents[3] / "infra/db/init.sql"
        self.conn.execute(source.read_text(encoding="utf-8-sig"))
        self.conn.execute(source.read_text(encoding="utf-8-sig"))
        self.start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(hours=3)

    def drop_schema(self):
        self.conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def price(self, hour, value):
        t = self.start + timedelta(hours=hour)
        return ("FI", t, t + timedelta(hours=1), "PT60M", Decimal(value), "EUR", "MWH")

    def weather(self, hour, value):
        return (self.start + timedelta(hours=hour), value, 40, 20, 4, 100)

    def test_price_replacement_and_estimated_flag(self):
        target = self.start + timedelta(hours=1)
        initial = [self.price(0, 10), self.price(2, 30)]
        save_checked_prices(self.conn, "FI", initial, self.start, self.end)
        query = "SELECT price, imputation_method FROM entsoe_day_ahead_prices WHERE bidding_zone='FI' AND period_start=%s"
        self.assertEqual(self.conn.execute(query, (target,)).fetchone(), (Decimal("20"), "boundary_mean"))
        view = "SELECT is_estimated FROM v_entsoe_prices_hourly WHERE bidding_zone='FI' AND hour_start=%s"
        self.assertEqual(self.conn.execute(view, (target,)).fetchone(), (True,))
        save_checked_prices(self.conn, "FI", [self.price(1, 17)], self.start, self.end)
        self.assertEqual(self.conn.execute(query, (target,)).fetchone(), (Decimal("17"), None))
        self.assertEqual(self.conn.execute(view, (target,)).fetchone(), (False,))
        save_checked_prices(self.conn, "FI", initial, self.start, self.end)
        self.assertEqual(self.conn.execute(query, (target,)).fetchone(), (Decimal("17"), None))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entsoe_day_ahead_prices").fetchone()[0], 3)

    def test_weather_replacement_and_no_overwrite_by_estimate(self):
        target = self.start + timedelta(hours=1)
        initial = [self.weather(0, 10), self.weather(2, 30)]
        dc = "FI-HELSINKI-01"
        save_checked_weather(self.conn, dc, initial, self.start, self.end)
        query = "SELECT temperature_2m, imputation_method FROM open_meteo_forecast WHERE datacenter_id=%s AND forecast_time=%s"
        self.assertEqual(self.conn.execute(query, (dc, target)).fetchone(), (Decimal("20"), "boundary_mean"))
        save_checked_weather(self.conn, dc, [self.weather(1, 17)], self.start, self.end)
        self.assertEqual(self.conn.execute(query, (dc, target)).fetchone(), (Decimal("17"), None))
        save_checked_weather(self.conn, dc, initial, self.start, self.end)
        self.assertEqual(self.conn.execute(query, (dc, target)).fetchone(), (Decimal("17"), None))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM open_meteo_forecast").fetchone()[0], 3)

    def test_bad_price_is_preserved_in_journal(self):
        bad = self.price(1, 9999)
        save_checked_prices(self.conn, "FI", [self.price(0, 10), bad, self.price(2, 30)], self.start, self.end)
        payload = self.conn.execute("SELECT payload FROM etl_dq_log WHERE reason='price_out_of_range'").fetchone()[0]
        self.assertEqual(Decimal(payload[4]), Decimal(9999))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entsoe_day_ahead_prices WHERE price=9999").fetchone()[0], 0)

if __name__ == "__main__":
    unittest.main()
