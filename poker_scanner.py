# -*- coding: utf-8 -*-
"""
poker_scanner.py — Скенер на hole карти от PokerStars прозорец.

Self-contained модул с graceful degradation: ако липсва dependency,
`CardScanner.available` е False и GUI-то disable-ва auto-scan без да
чупи основния advisor flow.

Архитектура:
    EasyOCR (primary)  → deep-learning CNN, най-точен на малки символи
    Tesseract (fallback) → ако EasyOCR не е инсталиран
    HSV color voting   → suit detection от rank corner
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ═══ Optional imports (graceful degradation) ═══════════════════════════
_IMPORT_ERR: Optional[str] = None

try:
    import numpy as np  # type: ignore
except Exception as e:  # pragma: no cover
    np = None
    _IMPORT_ERR = f"numpy: {e}"

try:
    import cv2  # type: ignore
except Exception as e:  # pragma: no cover
    cv2 = None
    if _IMPORT_ERR is None:
        _IMPORT_ERR = f"cv2: {e}"

try:
    import mss  # type: ignore
except Exception as e:  # pragma: no cover
    mss = None
    if _IMPORT_ERR is None:
        _IMPORT_ERR = f"mss: {e}"

try:
    from PIL import Image  # type: ignore
except Exception as e:  # pragma: no cover
    Image = None
    if _IMPORT_ERR is None:
        _IMPORT_ERR = f"Pillow: {e}"

try:
    import pygetwindow as gw  # type: ignore
except Exception as e:  # pragma: no cover
    gw = None
    if _IMPORT_ERR is None:
        _IMPORT_ERR = f"pygetwindow: {e}"

# Tesseract: optional fallback. Auto-detect binary на Windows.
TESSERACT_ERR: Optional[str] = None
try:
    import pytesseract  # type: ignore
    _tesseract_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for _p in _tesseract_paths:
        if _p and Path(_p).exists():
            pytesseract.pytesseract.tesseract_cmd = _p
            break
    else:
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            pytesseract = None
            TESSERACT_ERR = "Tesseract binary not found"
except Exception as e:
    pytesseract = None
    TESSERACT_ERR = f"pytesseract: {e}"

TESSERACT_OK = (pytesseract is not None and TESSERACT_ERR is None)

# EasyOCR: primary. Lazy reader init (първи call е ~12s, после cached).
EASYOCR_ERR: Optional[str] = None
_easyocr_module = None
_easyocr_reader = None
_easyocr_lock = threading.Lock()  # thread-safe init + inference
try:
    import easyocr as _easyocr_module  # type: ignore
except Exception as e:
    _easyocr_module = None
    EASYOCR_ERR = f"easyocr: {e}"

EASYOCR_AVAILABLE = (_easyocr_module is not None)


def _detect_gpu_available() -> bool:
    """Проверява има ли CUDA GPU за torch/easyocr (5-10× speedup)."""
    try:
        import torch  # type: ignore
        return bool(torch.cuda.is_available())
    except Exception:
        return False


_GPU_AVAILABLE = _detect_gpu_available()


def _enhance_for_ocr(img):
    """Sharpen + contrast boost върху upscaled карта преди OCR.

    Помага за rank glyph-ове които губят детайли при anti-aliasing:
      - Q губи опашчицата → чете се като 0 или T
      - 6 губи горната крива → чете се като T
      - 4 губи диагоналата → чете се като A
      - 7 губи hook-а → чете се като 1 или T

    Pipeline:
      1) Unsharp mask (Gaussian blur + weighted subtraction)
      2) CLAHE (local contrast) на L channel в LAB space

    Return: enhanced RGB array със същия shape.
    Cost: ~5-10ms на upscaled crop.
    """
    if np is None or cv2 is None:
        return img
    try:
        # 1. Unsharp mask: original - blurred = sharpened edges
        blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=1.5)
        sharpened = cv2.addWeighted(img, 1.7, blurred, -0.7, 0)

        # 2. CLAHE за local contrast на L channel (LAB space)
        lab = cv2.cvtColor(sharpened, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        l_enhanced = clahe.apply(l)
        lab_enhanced = cv2.merge([l_enhanced, a, b])
        return cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2RGB)
    except Exception:
        return img


def _get_easyocr_reader():
    """Thread-safe lazy init на EasyOCR Reader с auto GPU detection."""
    global _easyocr_reader
    if _easyocr_reader is not None:
        return _easyocr_reader
    if _easyocr_module is None:
        return None
    with _easyocr_lock:
        if _easyocr_reader is not None:
            return _easyocr_reader
        try:
            _easyocr_reader = _easyocr_module.Reader(
                ['en'], gpu=_GPU_AVAILABLE, verbose=False,
            )
        except Exception:
            # GPU init може да fail — retry със CPU
            try:
                _easyocr_reader = _easyocr_module.Reader(
                    ['en'], gpu=False, verbose=False,
                )
            except Exception:
                _easyocr_reader = None
    return _easyocr_reader


# ═══ Константи ═════════════════════════════════════════════════════════
HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "scanner_config.json"

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]
# "O" в allowlist — OCR често бърка Q с O (липсва опашката в Q).
# НЕ добавяме "I" защото OCR ще чете "10" като "IO" → грешен remap към J.
_VALID_OCR_CHARS = "AKQJT1098765432O"
_DIRECT_LETTERS = frozenset("AKQJT98765432")
_DIGIT_FALLBACK = frozenset("01")  # "0"/"1" → интерпретирани като "10" → T
# Character remap: O→Q (common Q misread).
# Прилага се САМО ако не е част от "10"/"1O" pattern (handle-нат отделно).
_OCR_CHAR_MAP = {"O": "Q"}

# Window discovery — table windows задължително съдържат един от тези маркери
_DEFAULT_WINDOW_NEEDLES = [
    "Влязъл като", "Logged in as", "Logged In As",
    "Holdem", "Hold'em", "Холдем",
    "Omaha", "Омаха", "Stud",
    "Mercury",
]

# Default calibration ratios (rank ъгъла на всяка карта, spрямо window)
DEFAULT_CALIBRATION: Dict[str, Any] = {
    "card1_x_ratio": 0.424,
    "card1_y_ratio": 0.752,
    "card2_x_ratio": 0.508,
    "card2_y_ratio": 0.752,
    "card_w_ratio": 0.030,
    "card_h_ratio": 0.080,
    # Rank-area (в card crop-а): горните 45% за rank detection.
    # detect_suit използва целия crop.
    "rank_area_ratio": [0.0, 0.0, 1.0, 0.45],
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "calibration": None,
    "scan_delay_ms": 500,
    "auto_confirm_threshold": 0.85,
    "confirm_threshold": 0.50,
    "window_title_match": "PokerStars",
}

# EasyOCR optimization: започваме от 6× (sweet spot). При confident hit
# (conf ≥ EARLY_EXIT_CONF) пропускаме останалите scales.
_OCR_SCALES = (6, 4, 8)
_OCR_EARLY_EXIT_CONF = 0.90


# ═══ Scanner ═══════════════════════════════════════════════════════════
class CardScanner:
    """Скенер на hole карти. Safe при липсващи deps (available=False)."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config_path = Path(config_path)

        self.available: bool = _IMPORT_ERR is None
        self.import_error: Optional[str] = _IMPORT_ERR

        self.config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self._load_config()

        self._last_detector: str = "?"
        # Provenance на последния EasyOCR read: "letter" | "ten_pattern" |
        # "digit_fallback" | None. Ползва се от detect_rank() за да реши
        # дали T↔6 shape override е валиден (само при "letter").
        self._last_ocr_source: Optional[str] = None

    # ── Config I/O ────────────────────────────────────────────────────
    def _load_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            for k, v in data.items():
                self.config[k] = v
        except Exception:
            pass  # корумпиран файл — ще се презапише при save

    def save_config(self) -> None:
        try:
            self.config_path.write_text(
                json.dumps(self.config, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    @property
    def calibration(self) -> Optional[Dict[str, Any]]:
        return self.config.get("calibration")

    @property
    def is_calibrated(self) -> bool:
        return (isinstance(self.calibration, dict)
                and "card1_x_ratio" in self.calibration)

    # ── Detection availability ────────────────────────────────────────
    @property
    def ocr_enabled(self) -> bool:
        return TESSERACT_OK

    @property
    def easyocr_enabled(self) -> bool:
        return EASYOCR_AVAILABLE

    @property
    def ocr_status(self) -> str:
        if EASYOCR_AVAILABLE:
            return f"EasyOCR {'GPU' if _GPU_AVAILABLE else 'CPU'} \u2713"
        if TESSERACT_OK:
            try:
                return f"Tesseract {pytesseract.get_tesseract_version()} \u2713"
            except Exception:
                return "Tesseract \u2713"
        return f"OCR \u2717 ({EASYOCR_ERR or TESSERACT_ERR or 'unknown'})"

    # ── Window discovery ──────────────────────────────────────────────
    def list_visible_windows(self) -> List[Tuple[str, Any]]:
        """Всички visible прозорци с non-empty title (за calibration picker)."""
        if gw is None:
            return []
        try:
            candidates = gw.getAllWindows()
        except Exception:
            return []
        result = []
        for w in candidates:
            try:
                title = (w.title or "").strip()
                if not title or w.width < 200 or w.height < 150:
                    continue
                if getattr(w, "isMinimized", False):
                    continue
            except Exception:
                continue
            result.append((title, w))
        return result

    @staticmethod
    def _matches_needle(title: str, needle: Any) -> bool:
        tl = title.lower()
        if isinstance(needle, list):
            return any(n.lower() in tl for n in needle if n)
        if isinstance(needle, str):
            return needle.lower() in tl
        return False

    @staticmethod
    def _window_usable(w) -> bool:
        try:
            if w.width <= 10 or w.height <= 10:
                return False
            if getattr(w, "isMinimized", False):
                return False
        except Exception:
            return False
        return True

    def find_ps_window(self):
        """Намира PokerStars table прозореца. Приоритет:
           1) exact title (от последна калибрация)
           2) configured needle keyword(s)
           3) default keywords
        """
        if gw is None:
            return None
        try:
            candidates = gw.getAllWindows()
        except Exception:
            return None

        exact = self.config.get("window_title_exact")
        needle = self.config.get("window_title_match")

        if exact:
            for w in candidates:
                try:
                    if (w.title or "") == exact and self._window_usable(w):
                        return w
                except Exception:
                    continue

        for search in (needle, _DEFAULT_WINDOW_NEEDLES):
            if not search:
                continue
            for w in candidates:
                try:
                    title = w.title or ""
                except Exception:
                    continue
                if self._matches_needle(title, search) and self._window_usable(w):
                    return w
        return None

    @staticmethod
    def window_rect(win) -> Optional[Tuple[int, int, int, int]]:
        if win is None:
            return None
        try:
            return (int(win.left), int(win.top),
                    int(win.width), int(win.height))
        except Exception:
            return None

    def set_target_window(self, title: str) -> None:
        """Запомня избрания прозорец (exact + fuzzy keyword)."""
        if not title:
            return
        self.config["window_title_exact"] = title
        fuzzy = title.split(" - ")[0].strip()
        if fuzzy and len(fuzzy) >= 3:
            self.config["window_title_match"] = fuzzy
        self.save_config()

    # ── Screenshot ────────────────────────────────────────────────────
    def capture_window(self, win) -> Optional["Image.Image"]:
        if mss is None or Image is None:
            return None
        rect = self.window_rect(win)
        if rect is None:
            return None
        left, top, w, h = rect
        if w <= 10 or h <= 10:
            return None
        try:
            with mss.mss() as sct:
                raw = sct.grab({"left": left, "top": top,
                                "width": w, "height": h})
                return Image.frombytes("RGB", raw.size, raw.rgb)
        except Exception:
            return None

    def capture_hole_region(
        self, win,
    ) -> Optional[Tuple["Image.Image", "Image.Image"]]:
        """Screenshot + crop на 2-те hole карти. Връща (card1, card2) или None."""
        if not self.is_calibrated:
            return None
        full = self.capture_window(win)
        if full is None:
            return None
        rect = self.window_rect(win)
        if rect is None:
            return None
        _, _, W, H = rect
        c = self.calibration or {}
        try:
            cw = int(c["card_w_ratio"] * W)
            ch = int(c["card_h_ratio"] * H)
        except (KeyError, TypeError):
            return None

        def crop_at(cx_r: float, cy_r: float) -> Optional["Image.Image"]:
            cx, cy = int(cx_r * W), int(cy_r * H)
            left, top = max(0, cx), max(0, cy)
            right, bottom = min(W, cx + cw), min(H, cy + ch)
            if right - left < 5 or bottom - top < 5:
                return None
            return full.crop((left, top, right, bottom))

        try:
            c1 = crop_at(c["card1_x_ratio"], c["card1_y_ratio"])
            c2 = crop_at(c["card2_x_ratio"], c["card2_y_ratio"])
        except KeyError:
            return None
        if c1 is None or c2 is None:
            return None
        return (c1, c2)

    # ── Calibration ───────────────────────────────────────────────────
    def calibrate_from_clicks(
        self,
        win_rect: Tuple[int, int, int, int],
        click1: Tuple[int, int],
        click2: Tuple[int, int],
    ) -> bool:
        """
        click1 = TOP-LEFT на rank ъгъла на 1-вата карта
        click2 = BOTTOM-RIGHT на rank ъгъла на 2-рата карта
        """
        left, top, W, H = win_rect
        if W <= 0 or H <= 0:
            return False
        x1_rel = (click1[0] - left) / W
        y1_rel = (click1[1] - top) / H
        x2_rel = (click2[0] - left) / W
        y2_rel = (click2[1] - top) / H
        total_w = x2_rel - x1_rel
        total_h = y2_rel - y1_rel
        if total_w <= 0 or total_h <= 0:
            return False

        # Rank-corner = 42% от total_w (оставя gap между картите)
        rank_w_r = total_w * 0.42
        rank_h_r = total_h
        self.config["calibration"] = {
            "card1_x_ratio": round(x1_rel, 4),
            "card1_y_ratio": round(y1_rel, 4),
            "card2_x_ratio": round(x2_rel - rank_w_r, 4),
            "card2_y_ratio": round(y1_rel, 4),
            "card_w_ratio": round(rank_w_r, 4),
            "card_h_ratio": round(rank_h_r, 4),
            "rank_area_ratio": list(DEFAULT_CALIBRATION["rank_area_ratio"]),
        }
        self.save_config()
        return True

    # ── Suit detection (HSV color voting) ─────────────────────────────
    def detect_suit(self, card_img: "Image.Image") -> Tuple[Optional[str], float]:
        """HSV-based suit detection.

        Sample-ваме ТОП strip (y: 2-30%) × ПЪЛНА ширина (x: 2-98%):
          - Top 30% съдържа САМО rank letter + suit symbol (и двата corner-а)
          - Face card figure е y≥25% → не попада в top 30%
          - Full width е важно: заради fan/overlap rendering-а в някои теми
            (Fanatica IX и др.) rank corner-ът на card2 НЕ е в top-left на
            crop-а, а е изместен вдясно (визуалната лява страна на картата
            е скрита под card1). Затова crop-ваме цяла top strip.

        Раньше използвахме top-left 2-38% × 2-55%, което работеше за
        card1 (винаги виждаш целия corner), но ПРОПУСКАШЕ rank corner-а
        на card2 при fan rendering → всяка card2 ставаше "♦" от purple felt AA.
        """
        if np is None or cv2 is None:
            return (None, 0.0)
        try:
            arr_full = np.array(card_img.convert("RGB"))
            H, W = arr_full.shape[:2]
            arr = arr_full[
                max(0, int(H * 0.02)): max(1, int(H * 0.30)),
                max(0, int(W * 0.02)): max(2, int(W * 0.98)),
            ]
            hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
            h = hsv[..., 0].astype(np.int32)
            s = hsv[..., 1].astype(np.int32)
            v = hsv[..., 2].astype(np.int32)

            # Exclude:
            #  - white (card surface): висок V, много нисък S
            #  - green felt: hue в зелено + desaturated + тъмен
            #  - gray felt: desaturated + средна яркост (различен theme/skin)
            # Цветното мастило на картата е saturated, така че S е основният
            # дискриминатор срещу филц/фон.
            is_white = (s < 25) & (v > 200)
            # Green felt: изискваме s >= 15 за да НЕ погълнем truly black ink pixels
            # (които имат s≈0 и случайна hue, често попадаща в [35,85] range).
            is_green_felt = (h > 35) & (h < 85) & (s >= 15) & (s < 70) & (v < 100)
            is_gray_felt = (s < 30) & (v >= 45) & (v < 170)
            # Purple/lavender felt — широк hue (130-170) НО ограничен по saturation.
            # Ключово: истинското синьо мастило на ♦ е силно saturated (s>120),
            # докато лилавият филц е по-ниско saturated (s<150, обикновено 40-120).
            is_purple_felt = (h >= 130) & (h <= 170) & (s > 20) & (s < 150)
            base = ~is_white & ~is_green_felt & ~is_gray_felt & ~is_purple_felt

            red = base & (((h <= 12) | (h >= 168)) & (s > 50) & (v > 80))
            # Blue (♦) — стеснен upper bound h<=122 (от 135). Purple felt AA
            # произвежда пиксели при h=126-127 с s=120-125, които под старото
            # правило се класифицираха като ♦. Реалното blue ink е винаги
            # при h<=120, така че 122 е safe upper bound.
            blue = base & (h >= 95) & (h <= 122) & (s > 120) & (v > 60)
            # Club green: saturated зелено, независимо от V.
            green = base & (h >= 35) & (h <= 90) & (s >= 60) & (v > 50)
            # Spade black: РЕЛАКСИРАНО до v<80 & s<50 (от v<45 & s<40).
            # Anti-aliasing на черното мастило върху purple/gray филц дава
            # пиксели с v=45-80 (не pure black). Старият праг пропускаше
            # повечето от тях и спадните карти не набираха гласове.
            black = base & (v < 80) & (s < 50)

            votes = {
                "h": int(red.sum()), "d": int(blue.sum()),
                "c": int(green.sum()), "s": int(black.sum()),
            }
            total = sum(votes.values())
            if total < 3:
                return (None, 0.0)
            best = max(votes, key=votes.get)
            sorted_v = sorted(votes.values(), reverse=True)
            dominance = (sorted_v[0] - sorted_v[1]) / max(total, 1)
            ratio = votes[best] / total
            conf = max(0.0, min(1.0, 0.5 * ratio + 0.5 * dominance + 0.2))
            return (best, conf)
        except Exception:
            return (None, 0.0)

    # ── Rank detection ────────────────────────────────────────────────
    def detect_rank(self, card_img: "Image.Image") -> Tuple[Optional[str], float]:
        """EasyOCR (primary) → Tesseract (fallback).

        Specific tiebreaker: EasyOCR често бърка "4" с "T" при ниска резолюция
        (горният хоризонтален бар на "4" наподобява "T"). Когато EasyOCR каже
        "T" с conf < 0.95, пускаме Tesseract за потвърждение; ако Tesseract
        върне "4" уверено → override към "4".
        """
        if EASYOCR_AVAILABLE:
            self._last_ocr_source = None
            r, c = self._detect_rank_easyocr(card_img)
            if r is not None and c >= 0.30:
                # 4↔T disambiguation: EasyOCR често чете "4" като "T" дори
                # с много висок conf (0.96+). Винаги проверяваме T с Tesseract;
                # ако Tesseract уверено чете "4" → override. Tesseract е по-точен
                # за цифри на малка резолюция, EasyOCR — за букви.
                if r == "T" and TESSERACT_OK:
                    tr, tc = self._detect_rank_tesseract(card_img)
                    if tr == "4" and tc >= 0.6:
                        self._last_detector = (
                            f"tesseract-override(conf={tc:.2f}, "
                            f"easyocr said T@{c:.2f})"
                        )
                        return (tr, tc)
                    # КРИТИЧНО: ако Tesseract също казва "T" (вкл. през "10"/"1O"
                    # pattern), това е силен сигнал че е истинско T/10, а не
                    # misread 6. Пропускаме shape override — иначе "10" глифът
                    # дава false positive (loop-ът на "0" симулира 6).
                    if tr == "T":
                        self._last_detector = (
                            f"easyocr+tess-T(conf={c:.2f}/{tc:.2f})"
                        )
                        return (r, c)
                    # Q↔T override: EasyOCR чете Q като T (малка опашка).
                    # КРИТИЧНО: само ако source е "letter" — т.е. EasyOCR наистина
                    # е прочел буквата "T". Ако source е "digit_fallback" (т.е.
                    # картата е "10" и EasyOCR е map-нал "10"/"1O" → T), това
                    # е истинско 10 — не override-вай.
                    # Иначе Tesseract халюцинира "Q" върху "10" глиф (тънката
                    # опашка на "0" + горната част наподобяват Q).
                    src_for_q = getattr(self, "_last_ocr_source", None)
                    if tr == "Q" and src_for_q == "letter":
                        self._last_detector = (
                            f"tess-Q-override(easyocr T@{c:.2f}, "
                            f"tess=Q@{tc:.2f})"
                        )
                        return ("Q", max(tc, 0.70))
                    # T↔6 disambiguation: EasyOCR понякога чете "6" като "T"
                    # (малка резолюция; тънка горна извивка на 6 не се вижда).
                    # Shape check: 6 има затворен loop долу, T няма никакви loops.
                    # Валидно е само ако EasyOCR е прочел реална буква "T"
                    # (не от "10"/"1O" pattern или "0" digit fallback).
                    src = getattr(self, "_last_ocr_source", None)
                    if src == "letter":
                        shape = self._detect_67_shape(card_img)
                        if shape == "6":
                            # Потвърди с Tesseract ако клони към 6
                            if tr in ("6", "G", "b"):
                                self._last_detector = (
                                    f"shape+tess-override(→6, "
                                    f"easyocr said T@{c:.2f}, tess={tr}@{tc:.2f})"
                                )
                                return ("6", max(tc, 0.80))
                            # Само shape: override, но с по-нисък conf
                            self._last_detector = (
                                f"shape-override(→6, easyocr said T@{c:.2f})"
                            )
                            return ("6", 0.75)
                    # За "ten_pattern" / "digit_fallback": само ако Tesseract
                    # много уверено каже 6/7 → override. Иначе keep T.
                    elif tr in ("6", "7") and tc >= 0.80 and src != "letter":
                        self._last_detector = (
                            f"tesseract-override(conf={tc:.2f}, "
                            f"easyocr said T via {src}@{c:.2f})"
                        )
                        return (tr, tc)
                # 6↔7 disambiguation: 6 и 7 се бъркат лесно на малки карти
                # (6 с тънка глава може да прилича на 7 с долна опашка).
                # Cross-check с Tesseract; ако Tesseract уверено каже
                # обратното → override. Shape-based fallback ако Tesseract fail-не.
                if r in ("6", "7") and TESSERACT_OK:
                    tr, tc = self._detect_rank_tesseract(card_img)
                    if tr in ("6", "7") and tr != r and tc >= 0.6:
                        # Tesseract уверено несъгласен — викаме shape check за tiebreak
                        shape = self._detect_67_shape(card_img)
                        winner = shape if shape in ("6", "7") else tr
                        self._last_detector = (
                            f"tesseract-override(conf={tc:.2f}, "
                            f"easyocr said {r}@{c:.2f}, shape={shape})"
                        )
                        return (winner, tc)
                    # Дори Tesseract да съгласи с EasyOCR, ако confs са различни,
                    # може да има shape check като safety за много ниски confs
                    if c < 0.85:
                        shape = self._detect_67_shape(card_img)
                        if shape in ("6", "7") and shape != r:
                            self._last_detector = (
                                f"shape-override({shape}, "
                                f"easyocr said {r}@{c:.2f})"
                            )
                            return (shape, 0.75)
                self._last_detector = f"easyocr(conf={c:.2f})"
                return (r, c)
        if TESSERACT_OK:
            r, c = self._detect_rank_tesseract(card_img)
            # По-нисък праг (0.3) — Tesseract е последна защита преди пълно fail
            if r is not None and c >= 0.3:
                self._last_detector = f"tesseract(conf={c:.2f})"
                return (r, c)
        self._last_detector = "failed"
        return (None, 0.0)

    def _detect_rank_easyocr(
        self, card_img: "Image.Image",
    ) -> Tuple[Optional[str], float]:
        """Multi-scale EasyOCR с early-exit при confident read.

        Логика:
          1) Опитваме scales в ред: 6× (sweet spot), 4×, 8×
          2) При direct letter read с conf ≥ 0.90 → връщаме веднага (skip остатъка)
          3) Ако никой scale не даде direct read с conf ≥ 0.90, връщаме най-добрия
             direct read събран от всички scales
          4) Ако НЯМА direct read, fallback на "0"/"1" → T reads

        Q често се чете като "0" на single scale (tail+loop сливат се в
        anti-aliasing). Multi-scale винаги хваща Q директно на поне един scale.
        """
        if np is None or cv2 is None or not EASYOCR_AVAILABLE:
            return (None, 0.0)
        reader = _get_easyocr_reader()
        if reader is None:
            return (None, 0.0)
        try:
            arr = np.array(card_img.convert("RGB"))
            H, W = arr.shape[:2]
            if H < 5 or W < 5:
                return (None, 0.0)

            # Tuples: (rank, conf, source)
            # source ∈ {"letter", "ten_pattern", "digit_fallback"}
            # Ползва се от detect_rank() за да знае дали T е от реална буква T
            # (→ eligible за T↔6 shape override) или от "10"/"0" (→ не се override-ва
            # защото "0" loop ще daде false positive "6").
            direct: List[Tuple[str, float, str]] = []
            digit_fallback: List[Tuple[str, float, str]] = []

            with _easyocr_lock:  # thread-safe inference
                for scale in _OCR_SCALES:
                    try:
                        up = cv2.resize(
                            arr, (W * scale, H * scale),
                            interpolation=cv2.INTER_CUBIC,
                        )
                        # Sharpen + contrast boost: усилва edge-овете на
                        # rank glyph-а за по-точен OCR. Евтино (~5-10ms).
                        # Помага особено при малки карти (66×80) където
                        # 6/Q/4/7 губят детайли при anti-aliasing.
                        up = _enhance_for_ocr(up)
                        results = reader.readtext(
                            up, allowlist=_VALID_OCR_CHARS, detail=1,
                        )
                    except Exception:
                        continue
                    if not results:
                        continue
                    # Rank е горе-вляво → sort by top-Y asc, conf desc
                    results.sort(key=lambda r: (r[0][0][1], -r[2]))
                    for (_bbox, text, conf) in results:
                        cleaned = "".join(ch for ch in text.upper()
                                          if ch in _VALID_OCR_CHARS)
                        if not cleaned:
                            continue
                        conf_f = float(conf)
                        # "10..." варианти → T (включително "1O" — O read като 0)
                        if (cleaned.startswith("10") or
                                cleaned.startswith("1O")):
                            direct.append(("T", conf_f, "ten_pattern"))
                            break
                        # "O1"/"O0" → T (cropped "10" read в обратен ред)
                        if cleaned.startswith("O") and len(cleaned) >= 2 and cleaned[1] in "01":
                            direct.append(("T", conf_f, "ten_pattern"))
                            break
                        # Multi-char с Q + O → истински Q (Q rank + glyph echo)
                        if "Q" in cleaned and "O" in cleaned:
                            direct.append(("Q", conf_f, "letter"))
                            break
                        ch = cleaned[0]
                        # Single-char "O": по-често е "0" (от "10") отколкото истински Q.
                        # Третираме като digit fallback → T. Ако реално е Q, Tesseract
                        # ще потвърди (неговият char map "O"→Q за single-char случаи).
                        if ch == "O" and len(cleaned) == 1:
                            digit_fallback.append(("T", conf_f, "digit_fallback"))
                            break
                        if ch in _DIRECT_LETTERS:
                            direct.append((ch, conf_f, "letter"))
                            break
                        if ch in _DIGIT_FALLBACK:
                            digit_fallback.append(("T", conf_f, "digit_fallback"))
                            break
                    # Early exit ако имаме confident direct read (letter)
                    if direct and direct[-1][1] >= _OCR_EARLY_EXIT_CONF:
                        r, c, src = direct[-1]
                        self._last_ocr_source = src
                        return (r, c)

            if direct:
                best = max(direct, key=lambda x: x[1])
                self._last_ocr_source = best[2]
                return (best[0], best[1])
            if digit_fallback:
                best = max(digit_fallback, key=lambda x: x[1])
                self._last_ocr_source = best[2]
                return (best[0], best[1])
            return (None, 0.0)
        except Exception:
            return (None, 0.0)

    def _detect_67_shape(self, card_img: "Image.Image") -> Optional[str]:
        """Shape-based 6/7 дисамбигация.

        Ключова разлика:
          - 6 има затворен loop в долната половина (inside pixels)
          - 7 е отворено (горна чертa + диагонал), няма затворен loop долу
          - "10" има ink в ДВА отделни блока (тънка "1" + "0") → abstain,
            защото "0" loop-ът ще даде false positive за 6

        Метод: взимаме rank-corner региона, threshold към binary, flood-fill от
        ъгъла (фона). Пиксели които НЕ са нито ink нито фон = вътрешност на 6.
        Ако долната половина има значителна вътрешност → 6, иначе → 7.
        Преди това правим columns-gap check за да отхвърлим "10" false positive.
        """
        if cv2 is None or np is None:
            return None
        try:
            arr = np.array(card_img.convert("L"))
            H, W = arr.shape[:2]
            # Rank corner — горната 75% × цялата ширина (за да хванем "10" изцяло)
            roi = arr[: int(H * 0.75), :]
            if roi.size == 0:
                return None
            # Upscale за по-добра shape analysis
            roi = cv2.resize(roi, (roi.shape[1] * 4, roi.shape[0] * 4),
                             interpolation=cv2.INTER_CUBIC)
            # Threshold: ink = тъмно, фон = светло
            _, binary = cv2.threshold(roi, 140, 255, cv2.THRESH_BINARY)
            h2, w2 = binary.shape

            # ── "10" detection: две отделни ink-колони с gap между тях ─────
            # Columns с ink (sum of black pixels per column)
            ink_mask = (binary == 0).astype(np.uint8)
            col_ink = ink_mask.sum(axis=0)
            # Threshold: колона "има ink" ако >= 5% от височината е ink
            col_threshold = max(3, int(h2 * 0.05))
            has_ink = col_ink >= col_threshold
            # Намираме contiguous runs
            runs: List[Tuple[int, int]] = []  # (start, end)
            in_run = False
            run_start = 0
            for i, v in enumerate(has_ink):
                if v and not in_run:
                    run_start = i
                    in_run = True
                elif not v and in_run:
                    runs.append((run_start, i))
                    in_run = False
            if in_run:
                runs.append((run_start, len(has_ink)))
            # Филтрираме тесни шум-runs (< 2 колони)
            runs = [(s, e) for (s, e) in runs if (e - s) >= 2]
            # Ако имаме 2+ sizeable runs с видим gap → "10" → abstain
            if len(runs) >= 2:
                # Само ако gap-ът е значителен (поне 3% от ROI)
                gaps = [runs[i + 1][0] - runs[i][1] for i in range(len(runs) - 1)]
                max_gap = max(gaps) if gaps else 0
                if max_gap >= max(3, int(w2 * 0.03)):
                    return None  # вероятно "10" — не правим 6/7 override

            # Също: ако ink-ът се простира през > 65% от ширината, най-вероятно
            # е двуцифрен rank ("10"), не 6/7
            ink_cols = int(has_ink.sum())
            if ink_cols > int(w2 * 0.65):
                return None

            # binary: ink=0 (black), background+interior=255 (white)
            # Flood-fill от (0,0) за да маркираме фона
            ff = binary.copy()
            mask = np.zeros((h2 + 2, w2 + 2), dtype=np.uint8)
            cv2.floodFill(ff, mask, (0, 0), 128)  # фон = 128
            # Сега: ink=0, фон=128, interior (затворени региони)=255
            interior = (ff == 255).astype(np.uint8)
            if interior.sum() == 0:
                return "7"  # няма затворена област → 7
            # Смятаме къде е interior-ът: горна половина vs долна
            top_half = interior[: h2 // 2, :].sum()
            bot_half = interior[h2 // 2 :, :].sum()
            total = top_half + bot_half
            if total < 20:
                return None  # твърде малко, не можем да кажем
            # 6 има loop долу, 9 — горе, 7 — няма. Тук само 6/7:
            if bot_half > top_half * 1.3 and bot_half > 30:
                return "6"
            return "7"
        except Exception:
            return None

    def _detect_rank_tesseract(
        self, card_img: "Image.Image",
    ) -> Tuple[Optional[str], float]:
        """Tesseract fallback. 6× upscale + binary + single PSM.

        По-прост от преди (без multi-PSM voting) — ползва се много рядко
        (само ако EasyOCR fail-не), и single PSM 10 (single char) е достатъчен.
        """
        if cv2 is None or np is None or pytesseract is None or Image is None:
            return (None, 0.0)
        try:
            gray = np.array(card_img.convert("L"))
            big = cv2.resize(gray, (gray.shape[1] * 6, gray.shape[0] * 6),
                             interpolation=cv2.INTER_CUBIC)
            _, binary = cv2.threshold(big, 180, 255, cv2.THRESH_BINARY)
            pil = Image.fromarray(binary)
            # Allowlist включва O, 0, 1 за да хване Q→O confusion.
            # НЕ добавяме I — би счупило "10"→T detection (10 → IO → J).
            cfg = "--psm 10 --oem 3 -c tessedit_char_whitelist=AKQJT98765432O10"
            text = pytesseract.image_to_string(pil, config=cfg).strip().upper()
            text = "".join(ch for ch in text if ch in "AKQJT0123456789O")
            if not text:
                return (None, 0.0)
            # Handle "10"/"1O" patterns first (T)
            if text.startswith("10") or text.startswith("1O"):
                return ("T", 0.7)
            ch = text[0]
            # Common single-char confusions
            ch = {"0": "T", "1": "T", "O": "Q"}.get(ch, ch)
            if ch in RANKS:
                return (ch, 0.7)  # fixed moderate confidence
            return (None, 0.0)
        except Exception:
            return (None, 0.0)

    # ── Dealer button detection ───────────────────────────────────────
    def detect_dealer_button(
        self, win=None, debug_dir: Optional[Path] = None,
    ) -> Optional[Dict[str, Any]]:
        """Търси D чипа в PokerStars прозорец чрез HoughCircles.

        D бутонът е малък бял/кремав диск с буква "D" в средата, ~20-35px
        в диаметър при обичаен размер на прозореца.

        Връща:
          {
            'x_ratio': float (0..1),  # позиция в рамките на window
            'y_ratio': float (0..1),
            'radius_px': int,
            'brightness': float (0..255),
            'confidence': float (0..1),
          }
        Или None ако нищо не е намерено.

        Ако debug_dir е подаден — записва annotated screenshot + raw там.
        """
        if not self.available or cv2 is None or np is None:
            return None
        if win is None:
            win = self.find_ps_window()
        if win is None:
            return None
        full = self.capture_window(win)
        if full is None:
            return None
        rect = self.window_rect(win)
        if rect is None:
            return None
        _, _, W, H = rect

        arr = np.array(full)  # RGB
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        # Blur малко да помогне HoughCircles
        blurred = cv2.medianBlur(gray, 5)

        # Радиус scale-ва с размера на прозореца. Типично D е 2-4% от
        # min(W,H). За 584×1396 window → 12-25 px.
        s = min(W, H)
        r_min = max(6, int(s * 0.015))
        r_max = max(r_min + 4, int(s * 0.040))

        try:
            circles = cv2.HoughCircles(
                blurred, cv2.HOUGH_GRADIENT, dp=1,
                minDist=int(s * 0.05),
                param1=80, param2=20,
                minRadius=r_min, maxRadius=r_max,
            )
        except Exception:
            circles = None

        if circles is None:
            if debug_dir is not None:
                self._save_dealer_debug(full, [], None, debug_dir)
            return None

        # Филтрираме кандидатите: яркост + разумни позиции
        cands: List[Dict[str, Any]] = []
        rejects: List[Dict[str, Any]] = []  # за debug: защо отпаднали
        circles = np.round(circles[0, :]).astype(int)

        # Областта на картите — изключваме я (H region)
        c = self.calibration or {}
        card_exclude = None
        try:
            cx1 = c["card1_x_ratio"] * W
            cx2 = c["card2_x_ratio"] * W
            cy = c["card1_y_ratio"] * H
            cw = c["card_w_ratio"] * W
            ch = c["card_h_ratio"] * H
            card_exclude = (
                min(cx1, cx2) - cw * 0.5,
                cy - ch * 0.2,
                max(cx1, cx2) + cw * 1.5,
                cy + ch * 1.2,
            )
        except (KeyError, TypeError):
            pass

        # Централна board+pot area — там НИКОГА няма D бутон, само board
        # карти и pot чипове (някои от които са червени → false positives).
        # x: 32-68%, y: 32-55% покрива board ред + chip stack ред.
        board_exclude = (
            W * 0.32, H * 0.32, W * 0.68, H * 0.55,
        )

        # За red-center check — конвертираме цялото до HSV веднъж
        hsv_full = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)

        for (cx, cy, r) in circles:
            base = {
                "cx": int(cx), "cy": int(cy), "r": int(r),
                "x_ratio": float(cx) / W, "y_ratio": float(cy) / H,
            }
            if cx < r or cy < r or cx + r >= W or cy + r >= H:
                rejects.append({**base, "reason": "out_of_bounds"})
                continue
            # EARLY EXCLUSIONS — преди скъпите HSV сметки
            # Изключи централната board+pot area
            bx1, by1, bx2, by2 = board_exclude
            if bx1 <= cx <= bx2 and by1 <= cy <= by2:
                rejects.append({**base, "reason": "in_board_area"})
                continue
            # Изключи hero card area
            if card_exclude:
                ex1, ey1, ex2, ey2 = card_exclude
                if ex1 <= cx <= ex2 and ey1 <= cy <= ey2:
                    rejects.append({**base, "reason": "in_card_area"})
                    continue
            # Изключи крайните ръбове (там са avatars, часовници, etc.)
            margin = 0.05
            if (cx < W * margin or cx > W * (1 - margin)
                    or cy < H * margin or cy > H * (1 - margin)):
                rejects.append({**base, "reason": "edge_margin"})
                continue

            # Яркост по външния ring (не център — D чипът има оцветен лог в център)
            ring_mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.circle(ring_mask, (cx, cy), r, 255, -1)
            cv2.circle(ring_mask, (cx, cy), max(1, int(r * 0.6)), 0, -1)
            ring_pixels = gray[ring_mask > 0]
            if ring_pixels.size == 0:
                rejects.append({**base, "reason": "empty_ring"})
                continue
            brightness = float(ring_pixels.mean())
            base["brightness"] = brightness
            # Пръстенът на D чипа е бял/кремав → brightness > 160
            # (свалено от 170 — реални бутони на тъмни теми падат до 165-170)
            if brightness < 160:
                rejects.append({**base, "reason": f"dim_ring<160 ({brightness:.0f})"})
                continue

            # RED CENTER CHECK — D чипът в PS има червен PokerStars лого.
            inner_mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.circle(inner_mask, (cx, cy), max(1, int(r * 0.55)), 255, -1)
            inner_h = hsv_full[..., 0][inner_mask > 0]
            inner_s = hsv_full[..., 1][inner_mask > 0]
            inner_v = hsv_full[..., 2][inner_mask > 0]
            if inner_h.size == 0:
                rejects.append({**base, "reason": "empty_center"})
                continue
            # Wider red range — някои теми имат orange-ish red star или
            # по-тъмен PS лого. h≤15 / h≥160, s>50, v>60.
            red_mask = (((inner_h <= 15) | (inner_h >= 160))
                        & (inner_s > 50) & (inner_v > 60))
            red_ratio = float(red_mask.sum()) / float(inner_h.size)
            base["red_ratio"] = red_ratio
            if red_ratio < 0.03:
                rejects.append({**base, "reason": f"no_red<3% ({red_ratio*100:.1f}%)"})
                continue

            cands.append({
                "cx": int(cx), "cy": int(cy), "r": int(r),
                "x_ratio": float(cx) / W, "y_ratio": float(cy) / H,
                "brightness": brightness,
                "red_ratio": red_ratio,
            })

        def _score(c_: Dict[str, Any]) -> float:
            b_norm = min(1.0, max(0.0, (c_["brightness"] - 160) / 95.0))
            r_norm = min(1.0, c_["red_ratio"] / 0.15)  # 15% red → full score
            return 0.4 * b_norm + 0.6 * r_norm

        # Добави score към всички кандидати (за debug sorting)
        for c_ in cands:
            c_["score"] = float(_score(c_))

        if not cands:
            if debug_dir is not None:
                self._save_dealer_debug(
                    full, circles.tolist(), None, debug_dir,
                    cands=[], rejects=rejects,
                    window_size=(W, H),
                    r_range=(r_min, r_max),
                    card_exclude=card_exclude,
                )
            return None

        best = max(cands, key=lambda c_: c_["score"])
        conf = best["score"]

        result = {
            "x_ratio": best["cx"] / W,
            "y_ratio": best["cy"] / H,
            "radius_px": best["r"],
            "brightness": best["brightness"],
            "red_ratio": best["red_ratio"],
            "confidence": float(conf),
            # За debug / UI — всички passed candidates sorted by score
            "candidates": sorted(cands, key=lambda c_: -c_["score"]),
            "rejected_count": len(rejects),
            "hough_total": int(len(circles)),
        }

        if debug_dir is not None:
            self._save_dealer_debug(
                full, circles.tolist(), result, debug_dir,
                cands=cands, rejects=rejects,
                window_size=(W, H),
                r_range=(r_min, r_max),
                card_exclude=card_exclude,
            )

        return result

    def _save_dealer_debug(
        self, img, all_circles, result, debug_dir: Path,
        cands: Optional[List[Dict[str, Any]]] = None,
        rejects: Optional[List[Dict[str, Any]]] = None,
        window_size: Optional[Tuple[int, int]] = None,
        r_range: Optional[Tuple[int, int]] = None,
        card_exclude: Optional[Tuple[float, float, float, float]] = None,
    ) -> None:
        """Debug helper — записва annotated screenshot + raw + текстов report.

        Annotated legend:
          - YELLOW thin circle: HoughCircles raw candidate (всички)
          - ORANGE: rejected (не е минал filter — brightness/red/margin/...)
          - GREEN: passed candidate (kept, но не е winner)
          - RED thick + text: WINNER (най-висок score)
        """
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            img.save(debug_dir / "dealer_raw.png")
            if cv2 is None or np is None:
                return
            arr = np.array(img)[:, :, ::-1].copy()  # RGB → BGR
            # Всички Hough candidates — тънко жълто
            for c in all_circles:
                cx, cy, r = int(c[0]), int(c[1]), int(c[2])
                cv2.circle(arr, (cx, cy), r, (0, 255, 255), 1)
            # Rejected — оранжеви с номер
            if rejects:
                for i, rej in enumerate(rejects):
                    cv2.circle(arr, (rej["cx"], rej["cy"]), rej["r"],
                               (0, 140, 255), 2)
                    cv2.putText(arr, f"X{i}", (rej["cx"] + rej["r"] + 3,
                                               rej["cy"] + 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                                (0, 140, 255), 1)
            # Passed (non-winner) — зелени с номер
            winner_key = None
            if result is not None and cands:
                winner_key = (result["x_ratio"], result["y_ratio"])
                for i, ca in enumerate(cands):
                    if (ca["x_ratio"], ca["y_ratio"]) == winner_key:
                        continue
                    cv2.circle(arr, (ca["cx"], ca["cy"]), ca["r"],
                               (0, 200, 0), 2)
                    cv2.putText(arr, f"P{i} s={ca.get('score',0):.2f}",
                                (ca["cx"] + ca["r"] + 3, ca["cy"] + 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 0), 1)
            if result is not None:
                W = arr.shape[1]; H = arr.shape[0]
                cx = int(result["x_ratio"] * W)
                cy = int(result["y_ratio"] * H)
                r = int(result["radius_px"])
                cv2.circle(arr, (cx, cy), r + 3, (0, 0, 255), 2)
                cv2.putText(
                    arr, f"WIN conf={result['confidence']:.2f}",
                    (cx + r + 5, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1,
                )
            cv2.imwrite(str(debug_dir / "dealer_annotated.png"), arr)

            # Текстов report — дето user-ът може копне и прати
            lines: List[str] = []
            if window_size:
                lines.append(f"window_size:   {window_size[0]}x{window_size[1]}")
            if r_range:
                lines.append(f"radius_search: {r_range[0]}..{r_range[1]} px")
            if card_exclude:
                lines.append(f"card_exclude:  x=[{card_exclude[0]:.0f}..{card_exclude[2]:.0f}] y=[{card_exclude[1]:.0f}..{card_exclude[3]:.0f}]")
            lines.append(f"hough_total:   {len(all_circles)} raw circles")
            lines.append(f"rejected:      {len(rejects) if rejects else 0}")
            lines.append(f"passed:        {len(cands) if cands else 0}")
            lines.append("")
            if cands:
                cs = sorted(cands, key=lambda c_: -c_.get("score", 0))
                lines.append("PASSED CANDIDATES (sorted by score):")
                lines.append(f"  {'#':>3} {'x%':>6} {'y%':>6} {'r':>4} "
                             f"{'bright':>7} {'red%':>6} {'score':>6} "
                             f"{'winner':>7}")
                for i, ca in enumerate(cs):
                    mark = "★" if (
                        result is not None
                        and (ca["x_ratio"], ca["y_ratio"]) == winner_key
                    ) else ""
                    lines.append(
                        f"  {i:>3d} "
                        f"{ca['x_ratio']*100:>5.1f}% "
                        f"{ca['y_ratio']*100:>5.1f}% "
                        f"{ca['r']:>4d} "
                        f"{ca['brightness']:>7.1f} "
                        f"{ca['red_ratio']*100:>5.1f}% "
                        f"{ca.get('score',0):>6.3f} "
                        f"{mark:>7}"
                    )
                lines.append("")
            if rejects:
                lines.append("REJECTED CANDIDATES (top 20 by brightness):")
                lines.append(f"  {'#':>3} {'x%':>6} {'y%':>6} {'r':>4} "
                             f"{'bright':>7} {'red%':>6} reason")
                rs = sorted(rejects,
                            key=lambda r_: -r_.get("brightness", 0))[:20]
                for i, rej in enumerate(rs):
                    b = rej.get("brightness", 0)
                    rr = rej.get("red_ratio", 0) * 100
                    lines.append(
                        f"  {i:>3d} "
                        f"{rej['x_ratio']*100:>5.1f}% "
                        f"{rej['y_ratio']*100:>5.1f}% "
                        f"{rej['r']:>4d} "
                        f"{b:>7.1f} "
                        f"{rr:>5.1f}% "
                        f"{rej['reason']}"
                    )
                lines.append("")
            if result is not None:
                lines.append(
                    f"WINNER: x={result['x_ratio']:.4f} "
                    f"y={result['y_ratio']:.4f} "
                    f"r={result['radius_px']} "
                    f"bright={result['brightness']:.1f} "
                    f"red={result['red_ratio']*100:.1f}% "
                    f"conf={result['confidence']:.3f}"
                )
            else:
                lines.append("WINNER: none (всички candidates отпаднали)")
            (debug_dir / "candidates.txt").write_text(
                "\n".join(lines), encoding="utf-8",
            )
        except Exception:
            pass

    # ── Public scan API ───────────────────────────────────────────────
    def scan(self, win=None) -> Optional[Dict[str, Any]]:
        """Сканира 2-те hole карти.

        Връща:
          {
            'cards': [(rank, suit), (rank, suit)],
            'confidence': min(rc, sc) across двете карти,
            'details': [(rank, rc, suit, sc), ...],
            'detectors': [str, str],
            'easyocr_available': bool,
            'tesseract_ok': bool,
          }
        Или None ако detection-ът напълно fail-ва.
        """
        if not self.available:
            return None
        if win is None:
            win = self.find_ps_window()
        if win is None:
            return None
        pair = self.capture_hole_region(win)
        if pair is None:
            return None

        cards: List[Tuple[str, str]] = []
        details: List[Tuple[str, float, str, float]] = []
        detectors: List[str] = []
        worst = 1.0
        for img in pair:
            self._last_detector = "?"
            rank, rc = self.detect_rank(img)
            suit, sc = self.detect_suit(img)
            if not rank or not suit:
                return None
            details.append((rank, rc, suit, sc))
            detectors.append(self._last_detector)
            cards.append((rank, suit))
            worst = min(worst, min(rc, sc))
        return {
            "cards": cards,
            "confidence": worst,
            "details": details,
            "detectors": detectors,
            "easyocr_available": EASYOCR_AVAILABLE,
            "tesseract_ok": TESSERACT_OK,
        }


# ═══ CLI sanity check ═════════════════════════════════════════════════
if __name__ == "__main__":
    s = CardScanner()
    print(f"available={s.available}  err={s.import_error}")
    print(f"calibrated={s.is_calibrated}  ocr={s.ocr_status}")
    w = s.find_ps_window()
    print(f"window={w}  rect={s.window_rect(w)}")
