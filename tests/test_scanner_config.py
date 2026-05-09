import json
import tempfile
import unittest
from pathlib import Path

import poker_scanner


ROOT = Path(__file__).resolve().parents[1]


class ScannerConfigTests(unittest.TestCase):
    def test_default_thresholds_match_runtime_policy(self):
        self.assertEqual(poker_scanner.DEFAULT_CONFIG["auto_confirm_threshold"], 0.30)
        self.assertEqual(poker_scanner.DEFAULT_CONFIG["confirm_threshold"], 0.15)

    def test_scanner_config_is_ignored_and_example_is_sanitized(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("scanner_config.json", gitignore)

        example = json.loads(
            (ROOT / "scanner_config.example.json").read_text(encoding="utf-8")
        )
        self.assertIsNone(example["calibration"])
        self.assertNotIn("window_title_exact", example)
        self.assertNotIn("nbglink", json.dumps(example, ensure_ascii=False).lower())
        self.assertTrue(example["template_matching_enabled"])
        self.assertEqual(example["template_rank_min_labels"], 10)
        self.assertEqual(example["template_suit_min_labels"], 4)

    @unittest.skipIf(
        poker_scanner.cv2 is None or poker_scanner.np is None or poker_scanner.Image is None,
        "OpenCV/Pillow unavailable",
    )
    def test_template_learning_and_matching_round_trip(self):
        from PIL import ImageDraw

        def make_card(rank, suit_letter):
            img = poker_scanner.Image.new("RGB", (80, 100), "white")
            draw = ImageDraw.Draw(img)
            draw.text((8, 4), rank, fill=(0, 0, 0))
            draw.text((8, 48), suit_letter, fill=(0, 0, 0))
            return img

        old_templates = poker_scanner.TEMPLATES_DIR
        with tempfile.TemporaryDirectory() as tmp:
            try:
                poker_scanner.TEMPLATES_DIR = Path(tmp) / "scanner_templates"
                scanner = poker_scanner.CardScanner(config_path=Path(tmp) / "config.json")
                scanner.config["template_rank_min_labels"] = 1
                scanner.config["template_suit_min_labels"] = 1

                ah = make_card("A", "H")
                ks = make_card("K", "S")
                written = scanner.learn_card_templates((ah, ks), [("A", "h"), ("K", "s")])
                self.assertEqual(written, 4)

                rank, rank_conf = scanner.detect_rank(ah)
                suit, suit_conf = scanner.detect_suit(ah)
                self.assertEqual(rank, "A")
                self.assertEqual(suit, "h")
                self.assertGreaterEqual(rank_conf, 0.78)
                self.assertGreaterEqual(suit_conf, 0.78)
            finally:
                poker_scanner.TEMPLATES_DIR = old_templates

    def test_no_templates_means_no_template_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_templates = poker_scanner.TEMPLATES_DIR
            try:
                poker_scanner.TEMPLATES_DIR = Path(tmp) / "scanner_templates"
                scanner = poker_scanner.CardScanner(config_path=Path(tmp) / "config.json")
                self.assertEqual(scanner._template_label_count("rank"), 0)
            finally:
                poker_scanner.TEMPLATES_DIR = old_templates


if __name__ == "__main__":
    unittest.main()
