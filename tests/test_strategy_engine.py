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


if __name__ == "__main__":
    unittest.main()
