from __future__ import annotations

import unittest
from datetime import date

from fi_toolbox import bondmath as bm


class BondMathTest(unittest.TestCase):
    def test_par_bond(self) -> None:
        settle = date(2026, 10, 15)
        maturity = date(2036, 10, 15)
        price = bm.price_from_yield(100, 5.0, 1, settle, maturity, 0.05)
        self.assertAlmostEqual(price["clean"], 100.0, places=6)
        self.assertAlmostEqual(price["dirty"], 100.0, places=6)
        self.assertAlmostEqual(price["accrued"], 0.0, places=6)

    def test_zero_coupon(self) -> None:
        price = bm.price_from_yield(100, 0.0, 1, date(2026, 10, 15), date(2027, 10, 15), 0.05)
        self.assertAlmostEqual(price["dirty"], 95.2381, places=3)

    def test_semi_annual(self) -> None:
        price = bm.price_from_yield(100, 5.0, 2, date(2026, 10, 15), date(2036, 6, 15), 0.06)
        self.assertAlmostEqual(price["clean"], 92.7367, places=3)
        self.assertAlmostEqual(price["accrued"], 1.6667, places=3)

    def test_ytm_roundtrip(self) -> None:
        args = (100, 5.0, 2, date(2026, 10, 15), date(2036, 6, 15))
        price = bm.price_from_yield(*args, 0.06)
        ytm = bm.ytm_from_clean(*args, price["clean"])
        self.assertAlmostEqual(ytm, 0.06, places=8)

    def test_duration_and_dv01(self) -> None:
        risk = bm.risk_metrics(100, 5.0, 1, date(2026, 10, 15), date(2036, 10, 15), 0.05)
        self.assertAlmostEqual(risk["macaulay"], 8.1078, places=3)
        self.assertAlmostEqual(risk["modified"], 7.7217, places=3)
        self.assertGreater(risk["dv01_per_100"], 0)

    def test_carry(self) -> None:
        carry = bm.carry_roll(100, 5.0, 1, date(2026, 10, 15), date(2036, 10, 15), 0.05, 90, 0.02, 0)
        self.assertGreater(carry["coupon_income"], carry["funding_cost"])
        self.assertGreater(carry["breakeven_bp"], 0)

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(bm.BondError):
            bm.coupon_schedule(date(2026, 1, 1), 1, date(2026, 2, 1))
        with self.assertRaises(bm.BondError):
            bm.price_from_yield(100, 5, 1, date(2026, 1, 1), date(2026, 1, 1), 0.05)


if __name__ == "__main__":
    unittest.main()
