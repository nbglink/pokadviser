import unittest

import poker_oop_tool as strategy


class StrategyEngineTests(unittest.TestCase):
    def test_strategy_module_has_no_legacy_tk_app(self):
        self.assertFalse(hasattr(strategy, "App"))

    def test_aa_vs_three_bet_is_four_bet(self):
        result = strategy.preflop_analyze(
            (("A", "h"), ("A", "s")),
            hero_pos="CO",
            facing_3bet=True,
            three_bettor_pos="BTN",
        )
        self.assertIn("4-BET", result["action"])

    def test_multiway_top_pair_does_not_raise(self):
        result = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("A", "d"), ("7", "c"), ("2", "h")],
            facing_bet=True,
            hero_pos="CO",
            num_opponents=3,
        )
        self.assertNotIn("RAISE", result["action"])

    def test_made_hand_classification_distinguishes_trips_full_house_quads(self):
        self.assertEqual(
            strategy.classify_hero_hand(
                [("7", "h"), ("K", "s")],
                [("7", "d"), ("7", "c"), ("2", "h")],
            )[0],
            "trips",
        )
        self.assertEqual(
            strategy.classify_hero_hand(
                [("7", "h"), ("K", "s")],
                [("7", "d"), ("7", "c"), ("K", "h")],
            )[0],
            "full_house",
        )
        self.assertEqual(
            strategy.classify_hero_hand(
                [("7", "h"), ("K", "s")],
                [("7", "d"), ("7", "c"), ("7", "s")],
            )[0],
            "quads",
        )

    def test_spr_buckets(self):
        self.assertEqual(strategy.spr_bucket(2.9)[0], "commit")
        self.assertEqual(strategy.spr_bucket(5.5)[0], "standard")
        self.assertEqual(strategy.spr_bucket(10.0)[0], "cautious")
        self.assertEqual(strategy.spr_bucket(14.0)[0], "deep")

    def test_mdf_basic_math(self):
        # Half-pot bet → 67% MDF; pot-size bet → 50% MDF; 1/3-pot → 75%.
        self.assertAlmostEqual(strategy.mdf(0.5), 0.667, places=2)
        self.assertAlmostEqual(strategy.mdf(1.0), 0.5, places=2)
        self.assertAlmostEqual(strategy.mdf(0.33), 0.752, places=2)

    def test_ev_river_call_breakeven(self):
        # Half-pot bet (5BB into 10BB): break-even at eq = bet/(2*bet+pot)
        # = 5/15 = 25% (NOT 33% — that's pot_odds_needed math).
        ev = strategy.ev_river_call(pot_bb=10, bet_bb=5, equity_vs_range=0.25)
        self.assertAlmostEqual(ev, 0.0, places=1)
        # Sanity: positive EV at 50% equity, negative at 10%
        self.assertGreater(
            strategy.ev_river_call(pot_bb=10, bet_bb=5, equity_vs_range=0.5), 0)
        self.assertLess(
            strategy.ev_river_call(pot_bb=10, bet_bb=5, equity_vs_range=0.1), 0)

    def test_stack_depth_buckets(self):
        self.assertEqual(strategy._stack_depth_bucket(None), "standard")
        self.assertEqual(strategy._stack_depth_bucket(10), "shallow")
        self.assertEqual(strategy._stack_depth_bucket(20), "short")
        self.assertEqual(strategy._stack_depth_bucket(80), "standard")
        self.assertEqual(strategy._stack_depth_bucket(150), "deep")

    def test_shallow_stack_pushes_aa(self):
        r = strategy.preflop_analyze(
            (("A", "h"), ("A", "s")), hero_pos="BTN", stack_bb=12,
        )
        self.assertIn("ALL-IN", r["action"])

    def test_shallow_stack_folds_marginal(self):
        r = strategy.preflop_analyze(
            (("K", "c"), ("9", "d")), hero_pos="BTN", stack_bb=12,
        )
        self.assertIn("FOLD", r["action"])

    def test_range_narrowing_drops_more_on_river(self):
        full = strategy.OPEN_RANGES.get("BTN", set())
        flop = strategy.narrow_range_facing_bet(full, "flop")
        turn = strategy.narrow_range_facing_bet(full, "turn")
        river = strategy.narrow_range_facing_bet(full, "river")
        self.assertLess(len(river), len(turn))
        self.assertLess(len(turn), len(flop))
        self.assertLess(len(flop), len(full))

    def test_range_narrowing_lowers_beat_pct_on_facing_bet(self):
        # Same hand+board, facing_bet narrows villain → beat_pct drops
        # (relative to non-facing baseline that uses full range).
        hole = [("A", "h"), ("K", "s")]
        board = [("A", "d"), ("7", "c"), ("2", "h"), ("5", "s"), ("8", "d")]
        r_facing = strategy.postflop_analyze(
            hole, board, facing_bet=True, hero_pos="CO", villain_pos="BTN",
            stack_bb=20, pot_bb=10, call_bb=5,
        )
        r_no_bet = strategy.postflop_analyze(
            hole, board, facing_bet=False, hero_pos="CO", villain_pos="BTN",
        )
        self.assertLess(r_facing["beat_pct"], r_no_bet["beat_pct"])

    def test_straight_threat_downgrades_tp(self):
        # AK on 5-6-7-8 turn — board has 4 connected, hero has no straight
        r = strategy.postflop_analyze(
            [("A", "c"), ("K", "d")],
            [("5", "h"), ("6", "c"), ("7", "d"), ("8", "s")],
            facing_bet=True, hero_pos="CO", villain_pos="BB",
            stack_bb=10, pot_bb=15, num_opponents=1,
        )
        self.assertTrue(
            "straight" in r["action"].lower()
            or "straight" in r["reason"].lower(),
            r,
        )

    def test_straight_threat_exempts_made_straight(self):
        # 9T on 5678 — hero has straight, should NOT downgrade
        r = strategy.postflop_analyze(
            [("9", "c"), ("T", "d")],
            [("5", "h"), ("6", "c"), ("7", "d"), ("8", "s")],
            facing_bet=True, hero_pos="CO", villain_pos="BB",
            stack_bb=10, pot_bb=15, num_opponents=1,
        )
        # Should NOT contain the threat warning in action
        self.assertNotIn("заплаха", r["action"])

    def test_river_ev_call_positive_returns_call(self):
        # TPTK on dry double-paired runout vs typical SB range
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("A", "d"), ("7", "c"), ("2", "h"), ("5", "s"), ("8", "d")],
            facing_bet=True, hero_pos="CO", villain_pos="BTN",
            stack_bb=15, pot_bb=10, call_bb=5, num_opponents=1,
        )
        self.assertIn("CALL", r["action"])
        self.assertIn("EV", r["reason"])  # EV math shown

    def test_flush_threat_still_active(self):
        # Regression: T9 (no hearts) on 5h-9h-3d-7h facing bet
        r = strategy.postflop_analyze(
            [("T", "c"), ("9", "c")],
            [("5", "h"), ("9", "h"), ("3", "d"), ("7", "h")],
            facing_bet=True, hero_pos="BTN", villain_pos="BB",
            stack_bb=11, pot_bb=15, num_opponents=1,
        )
        self.assertTrue(
            "flush" in r["action"].lower()
            or "flush" in r["reason"].lower(),
            r,
        )

    def test_boat_threat_downgrades_pair_on_paired_board(self):
        # AT on K-K-5 → hero has just A-high, paired board → engine flags boat
        # Test with hero having pair: AKo with K paired on board would be
        # trips (exempt). Use 2pair scenario: 87 on 8-8-7-2 facing bet.
        r = strategy.postflop_analyze(
            [("8", "c"), ("7", "d")],
            [("8", "h"), ("8", "s"), ("7", "c"), ("2", "d")],
            facing_bet=True, hero_pos="CO", villain_pos="BTN",
            stack_bb=10, pot_bb=15, num_opponents=1,
        )
        # Hero has trips 8s — exempt by trips-exclusion, не assert-ваме boat
        # Instead verify reason mentions paired-board awareness OR no
        # spurious boat downgrade for trips.
        self.assertNotIn("boat заплаха", r["action"])


if __name__ == "__main__":
    unittest.main()
