import unittest

from poker_live import (
    LiveAdvisor,
    LogWatcher,
    choose_dealer_candidate,
    decode_log_card,
    pos_name,
)


class LiveParserTests(unittest.TestCase):
    def make_watcher(self):
        watcher = LogWatcher()
        watcher.log_file = None
        watcher._reset_hand("42")
        return watcher

    def test_decode_numeric_and_text_cards(self):
        self.assertEqual(decode_log_card("14h"), ("A", "h"))
        self.assertEqual(decode_log_card("Td"), ("T", "d"))
        self.assertIsNone(decode_log_card(""))

    def test_position_names_support_9max_collapse(self):
        self.assertEqual(pos_name(0, 9), "BTN")
        self.assertEqual(pos_name(1, 9), "SB")
        self.assertEqual(pos_name(2, 9), "BB")
        self.assertEqual(pos_name(4, 9), "UTG")
        self.assertEqual(pos_name(6, 9), "MP")
        self.assertEqual(pos_name(8, 9), "CO")

    def test_log_blind_can_check_locks_bb_with_source(self):
        watcher = self.make_watcher()
        watcher._view_num_players = 6
        watcher.num_players = 6
        watcher._parse_actions("{a=c,vMn=0,vMx=0} {a=E,vMn=20000,vMx=100000}")
        self.assertEqual(watcher.hero_position, "BB")
        self.assertEqual(watcher.position_source, "log-can-check-BB")
        self.assertTrue(watcher._position_locked)
        self.assertEqual(watcher.bb_size, 10000)

    def test_log_small_blind_completion_locks_sb_with_source(self):
        watcher = self.make_watcher()
        watcher._view_num_players = 6
        watcher.num_players = 6
        watcher.bb_size = 10000
        watcher._parse_actions("{a=C,vMn=5000,vMx=0} {a=E,vMn=20000,vMx=100000}")
        self.assertEqual(watcher.hero_position, "SB")
        self.assertEqual(watcher.position_source, "log-complete-SB")
        self.assertTrue(watcher._position_locked)

    def test_fallback_position_keeps_source_and_unlocked_state(self):
        watcher = self.make_watcher()
        watcher._view_num_players = 6
        watcher.num_players = 6
        watcher._msg0020_count = 2
        watcher._calc_position_from_msg0020()
        self.assertEqual(watcher.hero_position, "CO")
        self.assertEqual(watcher.position_source, "fallback-count:2")
        self.assertFalse(watcher._position_locked)

    def test_position_source_labels_are_compact_for_status_bar(self):
        self.assertEqual(LiveAdvisor._position_source_label("log-can-check-BB"), "log")
        self.assertEqual(LiveAdvisor._position_source_label("dealer-button-scan"), "D")
        self.assertEqual(LiveAdvisor._position_source_label("fallback-count:2"), "count:2")

    def test_context_warnings_flag_uncertain_inputs(self):
        warnings = LiveAdvisor._context_warnings(
            position_source="fallback-count:2",
            hero_pos="CO",
            street="flop",
            facing=True,
            stack_bb=None,
            pot_bb=9.0,
            num_opponents=3,
            hole_source="scan",
            hole_confidence=0.42,
        )
        self.assertIn("pos fallback", warnings)
        self.assertIn("hole scan 42%", warnings)
        self.assertIn("stack unknown", warnings)
        self.assertIn("pot/SPR estimate", warnings)
        self.assertIn("multiway tighten", warnings)

    def test_guarded_action_requires_verify_for_uncertain_aggression(self):
        action, color = LiveAdvisor._guarded_action(
            "RAISE", "#00e676", "TP + K", warnings=["pos fallback"],
        )
        self.assertEqual(action, "VERIFY -> RAISE")
        self.assertEqual(color, "#ffcc66")

    def test_guarded_action_leaves_nutted_hands_clear(self):
        action, color = LiveAdvisor._guarded_action(
            "RAISE", "#00e676", "Boat 777 full of AA",
            hero_class="full_house", warnings=["pot/SPR estimate"],
        )
        self.assertEqual(action, "RAISE")
        self.assertEqual(color, "#00e676")

    def test_dealer_candidate_prefers_seat_fit_over_raw_visual_score(self):
        det = {
            "candidates": [
                {"x_ratio": 0.36, "y_ratio": 0.54, "r": 14, "score": 0.95},
                {"x_ratio": 0.35, "y_ratio": 0.4866, "r": 13, "score": 0.65},
            ]
        }
        chosen = choose_dealer_candidate(det, 6)
        self.assertAlmostEqual(chosen["x_ratio"], 0.35)
        self.assertEqual(chosen["pos"], "CO")
        self.assertLess(chosen["err"], 2)

    def test_board_parse_updates_street(self):
        watcher = self.make_watcher()
        watcher._parse("Hand { 42 } Board After { { 14h, 7c, 2d } }")
        self.assertEqual(watcher.board, [("A", "h"), ("7", "c"), ("2", "d")])
        self.assertEqual(watcher.street, "flop")
        watcher._parse("Hand { 42 } Board After { { 14h, 7c, 2d, 13s } }")
        self.assertEqual(watcher.street, "turn")


if __name__ == "__main__":
    unittest.main()
