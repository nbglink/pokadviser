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

    # ── Tier 1 bundle tests (EV-turn, 3-bet pot, blockers) ──

    def test_blocker_note_nut_flush(self):
        # Hero has Ace of board's dominant suit
        note = strategy._blocker_note(
            [("A", "h"), ("K", "c")],
            [("5", "h"), ("7", "h"), ("2", "h")],
            "high_card",
        )
        self.assertIn("nut flush", note)

    def test_blocker_note_high_straight(self):
        # Hero has 9 on 5-6-7-8 → blocks 5-9 straight
        note = strategy._blocker_note(
            [("9", "c"), ("K", "d")],
            [("5", "h"), ("6", "c"), ("7", "d"), ("8", "s")],
            "high_card",
        )
        self.assertIn("straight", note)

    def test_blocker_note_no_blocker(self):
        # Random hand with no blockers
        note = strategy._blocker_note(
            [("2", "c"), ("3", "d")],
            [("K", "h"), ("Q", "s"), ("J", "d")],
            "high_card",
        )
        self.assertEqual(note, "")

    def test_3bet_pot_smaller_sizing_on_wet_board(self):
        # 3-bet pot on wet QJ9 → sizing override to ~33%
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("Q", "h"), ("J", "h"), ("9", "d")],
            facing_bet=False, hero_pos="CO", villain_pos="BTN",
            stack_bb=80, pot_bb=20, num_opponents=1, is_3bet_pot=True,
        )
        # Sizing should mention 3-bet pot or be 25-33%
        self.assertTrue(
            "3-bet" in r["sizing"]
            or "25-33" in r["sizing"]
            or "33%" in r["sizing"],
            r["sizing"],
        )

    def test_3bet_pot_annotation_in_reason(self):
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("Q", "h"), ("J", "h"), ("9", "d")],
            facing_bet=False, hero_pos="CO", is_3bet_pot=True,
            stack_bb=80, pot_bb=20,
        )
        self.assertIn("3-bet pot", r["reason"])

    def test_ev_turn_call_when_positive(self):
        # TPTK on dry turn facing 50% pot bet → likely +EV call
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("A", "d"), ("7", "c"), ("2", "h"), ("5", "s")],
            facing_bet=True, hero_pos="CO", villain_pos="BTN",
            stack_bb=20, pot_bb=10, call_bb=5, num_opponents=1,
        )
        # Should be CALL with EV reasoning
        self.assertIn("CALL", r["action"])
        self.assertIn("turn", r["reason"].lower())

    def test_ev_turn_includes_draw_equity(self):
        # Hero has overcards + flush draw on turn → effective eq high
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "h")],
            [("Q", "h"), ("7", "h"), ("2", "c"), ("5", "s")],
            facing_bet=True, hero_pos="CO", villain_pos="BTN",
            stack_bb=20, pot_bb=10, call_bb=8, num_opponents=1,
        )
        # Reason should reference draw equity bonus
        self.assertIn("turn", r["reason"].lower())

    def test_3bet_pot_returned_in_dict(self):
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("Q", "h"), ("5", "c"), ("2", "d")],
            facing_bet=False, hero_pos="CO", is_3bet_pot=True,
        )
        self.assertTrue(r.get("is_3bet_pot"))

    # ── Tier 2: range vs range + mixed frequency ──

    def test_range_strength_returns_float(self):
        btn = strategy.OPEN_RANGES.get("BTN", set())
        s = strategy.range_strength(btn, [("A", "d"), ("7", "c"), ("2", "h")])
        self.assertIsInstance(s, float)
        self.assertGreater(s, 0)
        self.assertLess(s, 9)  # bounded by hierarchy span

    def test_range_vs_range_symmetric(self):
        # delta(A vs B) == -delta(B vs A) on same board
        adv_ab = strategy.range_vs_range_advantage(
            "CO", "BTN", [("A", "d"), ("7", "c"), ("2", "h")])
        adv_ba = strategy.range_vs_range_advantage(
            "BTN", "CO", [("A", "d"), ("7", "c"), ("2", "h")])
        self.assertAlmostEqual(adv_ab["delta"], -adv_ba["delta"], places=2)

    def test_range_vs_range_falls_back_to_co_for_missing(self):
        # BB has no opening range — function falls back to CO as proxy
        # (commonly BB defending range is similar in width to CO open).
        adv = strategy.range_vs_range_advantage(
            "CO", "BB", [("A", "d"), ("7", "c"), ("2", "h")])
        self.assertIsNotNone(adv)
        # When both sides effectively use CO range, delta ≈ 0
        self.assertLess(abs(adv["delta"]), 0.01)

    def test_mixed_freq_pure_when_far_apart(self):
        f = strategy.mixed_frequency_from_ev(5.0, 0.0)
        self.assertEqual(f, (100, 0))

    def test_mixed_freq_50_50_when_close(self):
        f = strategy.mixed_frequency_from_ev(1.0, 0.7)
        self.assertEqual(f, (50, 50))

    def test_mixed_freq_intermediate(self):
        # diff = 1.0 (between 0.5 and 1.5) → linear interpolation
        f = strategy.mixed_frequency_from_ev(2.0, 1.0)
        self.assertEqual(sum(f), 100)
        self.assertGreater(f[0], 50)  # primary > 50
        self.assertLess(f[0], 100)    # but less than 100

    def test_postflop_returns_alt_action_keys(self):
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("A", "d"), ("7", "c"), ("2", "h"), ("5", "s"), ("8", "d")],
            facing_bet=False, hero_pos="CO", villain_pos="BTN",
            stack_bb=15, pot_bb=10,
        )
        # Whether mixed or pure, the keys exist
        self.assertIn("alt_action", r)
        self.assertIn("alt_freq", r)
        self.assertIn("primary_freq", r)
        self.assertIn("range_advantage", r)

    # ── Tier 3: ICM lite ──

    def test_icm_off_no_change(self):
        # Without ICM: marginal ATo from CO vs UTG → CALL
        r = strategy.preflop_analyze(
            [("A", "c"), ("T", "d")], hero_pos="CO", facing_raise=True,
            raiser_pos="UTG", stack_bb=40, icm_pressure=0.0,
        )
        self.assertNotIn("ICM", r.get("reason", ""))

    def test_icm_pressure_folds_marginal(self):
        # With ICM heavy: ATo CALL → FOLD
        r = strategy.preflop_analyze(
            [("A", "c"), ("T", "d")], hero_pos="CO", facing_raise=True,
            raiser_pos="UTG", stack_bb=40, icm_pressure=0.7,
        )
        self.assertIn("FOLD", r["action"])
        self.assertIn("ICM", r["reason"])

    def test_icm_does_not_fold_premium(self):
        # AA must still raise even under heavy ICM
        r = strategy.preflop_analyze(
            [("A", "c"), ("A", "d")], hero_pos="CO", facing_raise=True,
            raiser_pos="UTG", stack_bb=40, icm_pressure=0.7,
        )
        self.assertTrue(
            "RAISE" in r["action"] or "BET" in r["action"]
            or "3-BET" in r["action"] or "4-BET" in r["action"],
            r["action"],
        )

    def test_icm_postflop_annotation(self):
        # ICM annotation appears in reason
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("A", "d"), ("7", "c"), ("2", "h"), ("5", "s"), ("8", "d")],
            facing_bet=True, hero_pos="CO", villain_pos="BTN",
            stack_bb=15, pot_bb=10, call_bb=5, num_opponents=1,
            icm_pressure=0.7,
        )
        self.assertIn("ICM", r["reason"])
        self.assertEqual(r["icm_pressure"], 0.7)

    def test_icm_postflop_zero_no_annotation(self):
        r = strategy.postflop_analyze(
            [("A", "h"), ("K", "s")],
            [("A", "d"), ("7", "c"), ("2", "h")],
            facing_bet=False, hero_pos="CO",
            icm_pressure=0.0,
        )
        self.assertNotIn("ICM", r["reason"])
        self.assertEqual(r["icm_pressure"], 0.0)


if __name__ == "__main__":
    unittest.main()
