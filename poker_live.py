"""
Poker Live Advisor — Hybrid approach:
  Board cards   = auto from PokerStars log (real-time)
  Hero position = auto from log actions + HH button tracking
  Hole cards    = quick 2-click manual input (rank + suit)
"""

import os
import re
import glob
import time
import threading
import tkinter as tk
from pathlib import Path
from poker_oop_tool import (
    preflop_analyze, postflop_analyze, hand_name, board_info, texture_tags,
)

# Centralized logging (advisor.log + scans.jsonl)
try:
    import poker_logger
    poker_logger.setup()
    _LOG = poker_logger.get_logger("live")
except Exception as _le:  # pragma: no cover
    poker_logger = None
    _LOG = None

# Optional scanner (graceful degradation if deps липсват)
try:
    from poker_scanner import CardScanner
    _SCANNER_IMPORT_ERR = None
except Exception as _e:  # pragma: no cover
    CardScanner = None
    _SCANNER_IMPORT_ERR = str(_e)
    if _LOG:
        _LOG.warning("[INIT] scanner import failed: %s", _e)

# Strategy event logger (decision + action JSONL за post-hoc анализ)
try:
    from poker_strategy_log import StrategyLogger
except Exception:  # pragma: no cover
    StrategyLogger = None

LOG_DIR = Path(r"C:\Users\Admin\AppData\Local\PokerStars.BG")

# ── Timing / threshold constants ───────────────────────────────────────
POLL_INTERVAL_MS = 300           # log watcher poll interval
CALIBRATE_POLL_MS = 30           # calibration click polling
DIALOG_POLL_MS = 100             # window-picker dialog polling
SCAN_CONFIRM_TIMEOUT_MS = 5000   # auto-reject middle-confidence scan

# Auto-scan retry: картите често са в анимация при първия опит → retry-и с
# escalating delays. Tuple от delays (ms) за всеки следващ retry.
# Общо wait: 500 + 600 + 900 = 2.0s преди да се предадем.
SCAN_RETRY_DELAYS_MS = (600, 900)
MAX_SCAN_ATTEMPTS = 1 + len(SCAN_RETRY_DELAYS_MS)  # 3 total

SYM = {'h': '\u2665', 'd': '\u2666', 'c': '\u2663', 's': '\u2660'}
SCLR = {'h': '#e83030', 'd': '#3080e0', 'c': '#30b050', 's': '#333333'}
RANK_MAP = {'2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',
            '10':'T','11':'J','12':'Q','13':'K','14':'A','1':'A'}
RANKS = ['A','K','Q','J','T','9','8','7','6','5','4','3','2']
SUITS = [('h','#e83030','\u2665'), ('d','#3080e0','\u2666'),
         ('c','#30b050','\u2663'), ('s','#333333','\u2660')]

POS_NAMES_6 = {0:'BTN', 1:'SB', 2:'BB', 3:'UTG', 4:'MP', 5:'CO'}
POS_NAMES_5 = {0:'BTN', 1:'SB', 2:'BB', 3:'UTG', 4:'CO'}
POS_NAMES_4 = {0:'BTN', 1:'SB', 2:'BB', 3:'CO'}
POS_NAMES_3 = {0:'BTN', 1:'SB', 2:'BB'}

# Визуални ъгли на местата спрямо масата (hero = south = -90°).
# Action върви по часовника (angle decreasing в ccw-позитивни координати):
# hero → bot-left → top-left → top → top-right → bot-right → hero.
# За N-max слотове: hero = slot 0, следващ clockwise = slot 1, и т.н.
# Offset от BTN се изчислява като hero_offset = (n - slot_of_btn) % n.
_SEAT_ANGLES_6 = {0: -90, 1: -150, 2: 150, 3: 90, 4: 30, 5: -30}
_SEAT_ANGLES_5 = {0: -90, 1: -162, 2: 126, 3: 54, 4: -18}
_SEAT_ANGLES_4 = {0: -90, 1: -180, 2: 90, 3: 0}
_SEAT_ANGLES_3 = {0: -90, 1: 150, 2: 30}


def _btn_slot_from_angle(angle_deg, num_players):
    """Map ъгъл (в градуси, 0=изток, 90=север) → visual seat slot (0..n-1).
    Slot 0 = hero (south). Избира най-близкия angular slot."""
    if num_players >= 6:
        angles = _SEAT_ANGLES_6
    elif num_players == 5:
        angles = _SEAT_ANGLES_5
    elif num_players == 4:
        angles = _SEAT_ANGLES_4
    else:
        angles = _SEAT_ANGLES_3

    def ang_diff(a, b):
        d = (a - b) % 360
        if d > 180:
            d -= 360
        return abs(d)

    best_slot = 0
    best_diff = 999.0
    for slot, ref in angles.items():
        d = ang_diff(angle_deg, ref)
        if d < best_diff:
            best_diff = d
            best_slot = slot
    return best_slot, best_diff


def position_from_dealer_ratio(x_ratio, y_ratio, num_players,
                               table_cx=0.5, table_cy=0.40):
    """Преобразува detected D позиция → hero position name.

    Връща (position_str, visual_slot, angle_deg, angular_error_deg).
    Ако angular_error > 30° → detection е unreliable (връщаме '?')."""
    import math
    dx = x_ratio - table_cx
    dy = table_cy - y_ratio  # flip Y (screen Y grows down)
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return ('?', -1, 0.0, 999.0)
    angle = math.degrees(math.atan2(dy, dx))
    slot, err = _btn_slot_from_angle(angle, num_players)
    if err > 30:
        return ('?', slot, angle, err)
    hero_offset = (num_players - slot) % num_players
    return (pos_name(hero_offset, num_players), slot, angle, err)


def decode_log_card(s):
    s = s.strip()
    if not s:
        return None
    m = re.match(r'^(\d+)([cdhs])$', s)
    if m:
        rank = RANK_MAP.get(m.group(1))
        if rank:
            return (rank, m.group(2))
    m = re.match(r'^([AKQJT2-9])([cdhs])$', s)
    if m:
        return (m.group(1), m.group(2))
    return None


def pos_name(offset_from_btn, num_players):
    """Get position name from offset (0=BTN, 1=SB, ...) and player count."""
    if num_players >= 6:
        return POS_NAMES_6.get(offset_from_btn, '?')
    elif num_players == 5:
        return POS_NAMES_5.get(offset_from_btn, '?')
    elif num_players == 4:
        return POS_NAMES_4.get(offset_from_btn, '?')
    else:
        return POS_NAMES_3.get(offset_from_btn, '?')


class LogWatcher:
    """Watches PokerStars log for board, new hands, actions, and position."""

    def __init__(self):
        self.last_pos = 0
        self.log_file = None

        # Current hand state
        self.hand_id = None
        self.board = []
        self.occupied_seats = []
        self.hero_position = None
        self.num_players = 0
        self.new_hand = False
        self.changed = False

        # Action tracking
        self.facing_bet = False
        self.call_amount = 0
        self.can_check = False
        self.street = 'preflop'
        self.folded_seats = set()
        self.bb_size = 0
        self.facing_raise_preflop = False
        self._preflop_base_call = None

        # Stack/pot tracking (за SPR)
        self.hero_stack_chips = 0   # ефективен stack на hero в chips (derived от vMx)
        self.pot_chips = 0          # текущ pot в chips (approx, натрупан от действия)
        self._pot_preflop_baseline = 0  # pot at start of postflop street

        # Hero action tracking (за strategy logger)
        self.last_hero_action = None    # {"code","amount","seq"}
        self.hero_action_new = False    # flag: ново действие от hero за консумиране

        # Position detection via MSG_0020 counting
        self._msg0020_count = 0
        self._position_locked = False
        self._action_count_saved = None  # saved count when MSG_0007 fires before View
        self._view_num_players = 0       # player count from View Players line
        # Seats that took a preflop action (Nu+ or transitioned to Nn+) —
        # supplements MSG_0020 counting which misses pre-actions in Zoom.
        self._preflop_action_seats = set()
        self._last_folded_seats = set()  # tracked across view lines

        self._find_log()

    def _find_log(self):
        logs = sorted(LOG_DIR.glob("PokerStars.log.*"), key=os.path.getmtime, reverse=True)
        if logs:
            self.log_file = logs[0]
            self.last_pos = os.path.getsize(self.log_file)

    def _calc_position_from_msg0020(self, count=None):
        """Calculate hero position from action counts (HEURISTIC fallback).

        Uses max of MSG_0020 count and distinct preflop action seats count.
        MSG_0020 often misses pre-actions in Zoom (e.g., call-any),
        but the view-based Nu+/Nn+ tracking captures those.

        Formula: offset_from_btn = (3 + k) % num_players
        Does NOT lock position — allow a=c/SB vMin signals to override.
        """
        n = self._view_num_players or self.num_players
        if n < 2:
            return
        k_msg = count if count is not None else self._msg0020_count
        k_view = len(self._preflop_action_seats)
        k = max(k_msg, k_view)
        offset = (3 + k) % n
        self.hero_position = pos_name(offset, n)
        self.num_players = n
        # NOTE: no _position_locked = True here — counting is unreliable.
        # Only lock when we have definitive signals (blind post or a=c/SB vMin).

    def _reset_hand(self, hid):
        """Reset all state for a new hand."""
        self.hand_id = hid
        self.board = []
        self.occupied_seats = [0]  # hero always seat 0
        self.hero_position = None
        self.num_players = 0
        self.new_hand = True
        self.facing_bet = False
        self.facing_raise_preflop = False
        self.call_amount = 0
        self.can_check = False
        self.street = 'preflop'
        self.folded_seats = set()
        self._preflop_base_call = None
        self._msg0020_count = 0
        self._position_locked = False
        self._action_count_saved = None
        self._view_num_players = 0
        self._preflop_action_seats = set()
        self._last_folded_seats = set()
        self.hero_stack_chips = 0
        self.pot_chips = 0
        self._pot_preflop_baseline = 0
        self.last_hero_action = None
        self.hero_action_new = False
        self.changed = True

    def poll(self):
        if not self.log_file or not self.log_file.exists():
            self._find_log()
            if not self.log_file:
                return False
        try:
            sz = os.path.getsize(self.log_file)
            if sz < self.last_pos:
                self._find_log()
                self.last_pos = 0
            if sz <= self.last_pos:
                return False

            with open(self.log_file, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(self.last_pos)
                lines = f.readlines()
                self.last_pos = f.tell()

            self.changed = False
            self.new_hand = False
            for line in lines:
                self._parse(line)

            return self.changed
        except (IOError, PermissionError):
            return False

    def _parse(self, line):
        # ── New hand: MSG_0080 (most reliable new hand signal) ──
        m = re.search(r'Hand \{ (\d+) \} => MSG_0080', line)
        if m:
            hid = m.group(1)
            if hid != self.hand_id:
                self._reset_hand(hid)
            return

        # ── Player gets cards (track occupied seats) ──
        m = re.search(r'Hand \{ (\d+) \} Player \{ (\d+) \} Cards \{ \d', line)
        if m and m.group(1) == self.hand_id:
            seat = int(m.group(2))
            if seat not in self.occupied_seats:
                self.occupied_seats.append(seat)
                self.occupied_seats.sort()
                self.num_players = len(self.occupied_seats)
                self.changed = True
            return

        # ── Player folds (cards removed) ──
        m = re.search(r'Hand \{ (\d+) \} Player \{ (\d+) \} Cards \{\}', line)
        if m and m.group(1) == self.hand_id:
            seat = int(m.group(2))
            self.folded_seats.add(seat)
            self.changed = True
            return

        # ── View Players — accurate active player count ──
        # Format: Players { { c0, c1 }, -, { --, -- }, ... } initial=0
        # { ... } = active, - = empty/sitting out
        m = re.search(r'Hand \{ (\d+) \} Players \{ (.+?) \} initial=', line)
        if m and m.group(1) == self.hand_id and self._view_num_players == 0:
            vcount = len(re.findall(r'\{[^}]+\}', m.group(2)))
            if vcount >= 2:
                self._view_num_players = vcount
                self.num_players = vcount
                # If MSG_0007 already fired but View hadn't arrived yet, calc now
                if self._action_count_saved is not None and not self._position_locked:
                    self._calc_position_from_msg0020(self._action_count_saved)
                    self.changed = True
            return

        # ── View Players state (per-seat L/N u/o/n +) — track preflop action ──
        # Format: Players {  0:Lo+ ... 1:No+ ... 2:Nn+ ... 3:Nu+ ... }
        #  Lo+ = hero has cards; Lu+ = hero is UP
        #  No+ = other has cards, not up; Nu+ = other is UP; Nn+ = other folded
        # Track seats that act (Nu+) or transition to Nn+ (newly folded).
        m = re.search(r'Hand \{ (\d+) \}.+?Players \{ +(0:[LN][a-z]\+.*?)\}',
                      line)
        if (m and m.group(1) == self.hand_id
                and self.street == 'preflop'
                and not self._position_locked):
            state_str = m.group(2)
            current_folded = set()
            for sm in re.finditer(r'(\d+):([LN])([ounu])\+', state_str):
                seat = int(sm.group(1))
                kind, sub = sm.group(2), sm.group(3)
                # Track Nu+ (currently up = acting) as having acted
                if kind == 'N' and sub == 'u':
                    self._preflop_action_seats.add(seat)
                # Track newly folded seats
                if kind == 'N' and sub == 'n':
                    current_folded.add(seat)
            # New folds since last view → count as actions
            new_folds = current_folded - self._last_folded_seats
            self._preflop_action_seats.update(new_folds)
            self._last_folded_seats = current_folded
            return

        # ── MSG_0020 — another player acted (count for position) ──
        m = re.search(r'Hand \{ (\d+) \} => MSG_0020 \{', line)
        if m and m.group(1) == self.hand_id and not self._position_locked:
            self._msg0020_count += 1
            return

        # ── Action Complete — hero завърши действие (за strategy logger) ──
        # Format: Hand { N } Action Complete { 0 : msgid=ACT(X),a=Y,v=N,seq=S,flags=F }
        m = re.search(
            r'Hand \{ (\d+) \} Action Complete \{ 0 : msgid=ACT\(\d+\),'
            r'a=(\w),v=(\d+),seq=(\d+)',
            line,
        )
        if m and m.group(1) == self.hand_id:
            self.last_hero_action = {
                "code": m.group(2),
                "amount": int(m.group(3)),
                "seq": int(m.group(4)),
            }
            self.hero_action_new = True
            # Не правим return — можем да имаме и други pattern-и в същата линия

        # ── MSG_0007 — action options for hero ──
        m = re.search(r'Hand \{ (\d+) \} => MSG_0007 \{ seq: \d+ \{ (.+?) \} \}', line)
        if m and m.group(1) == self.hand_id:
            self._parse_actions(m.group(2))
            return

        # ── GameControls Actions ──
        if self.hand_id:
            m = re.search(r'Hand \{ ' + re.escape(self.hand_id) + r' \} GameControls Actions \{ \{(.+?)\} \}', line)
            if m:
                self._parse_game_controls(m.group(1).strip())
                return

        # ── Board cards (real-time) ──
        m = re.search(r'Board (?:Before|After) \{ \{ ([^}]+) \} \}', line)
        if m:
            cards_str = m.group(1).split(',')
            new_board = [decode_log_card(cs.strip()) for cs in cards_str]
            new_board = [c for c in new_board if c]
            if new_board and new_board != self.board:
                self.board = new_board
                if len(self.board) == 3:
                    self.street = 'flop'
                elif len(self.board) == 4:
                    self.street = 'turn'
                elif len(self.board) == 5:
                    self.street = 'river'
                self.facing_bet = False
                self.call_amount = 0
                self.can_check = True
                self.changed = True
            return

        if re.search(r'Board After \{\}', line):
            if self.board:
                self.board = []
                self.changed = True

    def _parse_actions(self, s):
        """Parse MSG_0007 details."""
        self.can_check = False
        self.facing_bet = False
        self.call_amount = 0
        raise_vmin = 0   # a=E vMin — min-raise amount (tells us BB in unraised pot)
        bet_vmin = 0     # a=B vMin — min-bet (postflop)

        for m in re.finditer(r'\{a=(\w),vMn=(\d+),vMx=(\d+)', s):
            act, v_min, v_max = m.group(1), int(m.group(2)), int(m.group(3))
            if act == 'c':
                self.can_check = True
            elif act == 'C' and 0 < v_min < 4000000000:
                self.call_amount = v_min
                self.facing_bet = True
            elif act == 'E' and v_min > 0:
                raise_vmin = v_min
                # vMx на E (raise) = max raise = оставащ стак на hero
                if 0 < v_max < 4000000000:
                    self.hero_stack_chips = v_max
            elif act == 'B' and v_min > 0:
                bet_vmin = v_min
                # vMx на B (bet) = max bet = оставащ стак
                if 0 < v_max < 4000000000:
                    self.hero_stack_chips = v_max
            elif act == 'P':  # post BB (non-Zoom only)
                self.hero_position = 'BB'
                self._position_locked = True
                self.bb_size = v_min
            elif act == 'p':  # post SB (non-Zoom only)
                self.hero_position = 'SB'
                self._position_locked = True
                if self.bb_size == 0:
                    self.bb_size = v_min * 2

        # ── Learn BB size from available signals ──────────────────
        # 1. Preflop + can_check + a=E vMin present → vMin = 2*BB (min-raise)
        # 2. Preflop facing just BB (no raise yet) → call_amount = BB
        # 3. Postflop: bet_vmin = BB (min-bet equals BB)
        if self.bb_size == 0:
            if self.street == 'preflop':
                if self.can_check and raise_vmin > 0:
                    self.bb_size = raise_vmin // 2
                elif self.facing_bet and self._preflop_base_call is None:
                    # First preflop bet hero faces = unraised BB
                    # But we can't be sure yet; defer
                    pass
            else:
                # Postflop min-bet = BB
                if bet_vmin > 0:
                    self.bb_size = bet_vmin

        # Still unknown BB? Fall back to call amount
        if self.bb_size == 0 and self.call_amount > 0:
            self.bb_size = self.call_amount

        # ── Detect hero blinds from action options (Zoom-reliable) ──
        # BB: can_check preflop → BB (nobody raised)
        # BB: facing bet preflop AND call_amount divisible by BB AND
        #     raise_vmin - call_amount == BB (signature: BB already posted)
        # SB: call_amount NOT divisible by BB (odd fraction of BB)
        if self.street == 'preflop' and not self._position_locked:
            if self.can_check:
                # Check preflop is only possible for BB in unraised pot
                self.hero_position = 'BB'
                self._position_locked = True
            elif (self.facing_bet and self.bb_size > 0
                  and self.call_amount == self.bb_size // 2):
                # vMin exactly = SB → SB completing to BB in unraised pot.
                # (Narrow condition to avoid false positives from non-standard
                #  raises that happen to be odd fractions of BB.)
                self.hero_position = 'SB'
                self._position_locked = True

        # Track preflop raises
        if self.street == 'preflop' and self.facing_bet:
            if self._preflop_base_call is None:
                self._preflop_base_call = self.call_amount
            elif self.call_amount > self._preflop_base_call:
                self.facing_raise_preflop = True

        # Position fallback: counting-based (unreliable in Zoom due to
        # pre-actions) when no definitive blind-option signal fired.
        if not self._position_locked:
            self._calc_position_from_msg0020(self._msg0020_count)

        self.changed = True

    def _parse_game_controls(self, s):
        """Parse GameControls Actions simplified format."""
        self.can_check = False
        old_facing = self.facing_bet
        self.facing_bet = False

        for p in s.split(','):
            tokens = p.strip().split()
            if len(tokens) >= 2:
                act = tokens[0]
                val = int(tokens[1]) if tokens[1].isdigit() else 0
                if act == 'c':
                    self.can_check = True
                elif act == 'C' and val > 0:
                    self.call_amount = val
                    self.facing_bet = True

        if self.street == 'preflop' and self.facing_bet:
            if self._preflop_base_call is None:
                self._preflop_base_call = self.call_amount
            elif self.call_amount > self._preflop_base_call:
                self.facing_raise_preflop = True

        # NOTE: we intentionally don't calc position from GameControls —
        # GameControls fires speculatively with empty/partial data during
        # other players' actions. Position calc lives in _parse_actions
        # (MSG_0007 path) only, where state is authoritative.

        if self.facing_bet != old_facing:
            self.changed = True


# ─── GUI ──────────────────────────────────────────────────────────────────────
class LiveAdvisor(tk.Tk):
    BG = "#1a2e1e"
    BG2 = "#0f1f14"
    GOLD = "#f0d060"
    CARD_BG = "#ffe040"

    POS_COLORS = {
        'BTN': '#40e040', 'CO': '#80d040', 'MP': '#c0c040',
        'UTG': '#e0a040', 'SB': '#e06040', 'BB': '#d04040'
    }

    def __init__(self):
        super().__init__()
        self.title("\u2660 POKER ADVISOR")
        self.configure(bg=self.BG)
        self.attributes('-topmost', True)
        self.attributes('-alpha', 0.95)
        self.resizable(True, True)
        self.minsize(500, 400)

        self.watcher = LogWatcher()
        self.hole_cards = []
        self.pending_rank = None

        # Strategy logger — записва decision points + hero actions в JSONL
        self.strategy_logger = StrategyLogger() if StrategyLogger else None

        # Scanner (optional) — disabled by default
        self.scanner = CardScanner() if CardScanner else None
        self.scanner_err = _SCANNER_IMPORT_ERR
        self._scan_after_id = None
        self._confirm_after_id = None
        self._pending_scan = None  # dict or None
        self._last_scanned_hand_id = None
        self._scan_in_progress = False  # true докато worker thread scan-ва
        self._scan_attempt = 0          # retry counter за текущата ръка
        # Logger state: scan_id of most-recent scan for current hand — ползва
        # се за correction attribution когато user въведе ръчни карти.
        self._last_scan_id = None
        self._last_scan_hand_id = None
        if _LOG:
            _LOG.info("[INIT] LiveAdvisor started; scanner=%s",
                      "OK" if self.scanner and self.scanner.available
                      else "unavailable")

        self._build()
        self._poll()

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=self.BG2, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="\u2660 POKER ADVISOR", bg=self.BG2, fg=self.GOLD,
                 font=("Segoe UI", 18, "bold")).pack(side="left", padx=12)
        self.status_var = tk.StringVar(value="Waiting for hand...")
        tk.Label(hdr, textvariable=self.status_var, bg=self.BG2, fg="#88aa88",
                 font=("Segoe UI", 11)).pack(side="right", padx=12)

        # Scanner row (auto-scan toggle + calibrate + training counter)
        sbar = tk.Frame(self, bg=self.BG2, pady=4)
        sbar.pack(fill="x")
        scanner_ok = self.scanner is not None and self.scanner.available
        self.auto_scan_var = tk.BooleanVar(value=False)
        cb_state = "normal" if scanner_ok else "disabled"
        tip = "" if scanner_ok else f" (missing: {self.scanner_err or 'scanner'})"
        self.auto_scan_cb = tk.Checkbutton(
            sbar, text="\U0001F50D Auto-scan" + tip, variable=self.auto_scan_var,
            bg=self.BG2, fg="#cccccc", activebackground=self.BG2,
            selectcolor="#2a3a2a", font=("Segoe UI", 10, "bold"), state=cb_state,
            command=self._on_toggle_autoscan,
        )
        self.auto_scan_cb.pack(side="left", padx=12)

        self.calib_btn = tk.Button(
            sbar, text="Калибрирай", font=("Segoe UI", 9, "bold"),
            bg="#2a3a4a", fg="white", activebackground="#3a5a7a",
            relief="flat", bd=0, padx=8, pady=2,
            command=self._calibrate_dialog, state=cb_state,
        )
        self.calib_btn.pack(side="left", padx=4)

        self.scan_now_btn = tk.Button(
            sbar, text="Scan now", font=("Segoe UI", 9, "bold"),
            bg="#2a5a3a", fg="white", activebackground="#3a7a4a",
            relief="flat", bd=0, padx=8, pady=2,
            command=self._manual_scan, state=cb_state,
        )
        self.scan_now_btn.pack(side="left", padx=2)

        self.debug_btn = tk.Button(
            sbar, text="\U0001F41B", font=("Segoe UI", 9, "bold"),
            bg="#5a4a2a", fg="white", activebackground="#7a6a3a",
            relief="flat", bd=0, padx=6, pady=2,
            command=self._debug_scan, state=cb_state,
        )
        self.debug_btn.pack(side="left", padx=2)

        # BTN scan: опитва да детектира D чипа → hero position
        self.btn_scan_btn = tk.Button(
            sbar, text="D?", font=("Segoe UI", 9, "bold"),
            bg="#2a3a5a", fg="white", activebackground="#3a4a7a",
            relief="flat", bd=0, padx=6, pady=2,
            command=self._scan_dealer_button, state=cb_state,
        )
        self.btn_scan_btn.pack(side="left", padx=2)

        # OCR status (read-only label: напр. "EasyOCR GPU ✓")
        self.ocr_status_var = tk.StringVar(value="")
        tk.Label(sbar, textvariable=self.ocr_status_var, bg=self.BG2,
                 fg="#88aa88", font=("Segoe UI", 9)).pack(side="left", padx=8)

        # Scan confirm area (hidden until pending scan exists)
        self.scan_confirm_var = tk.StringVar(value="")
        self.scan_confirm_frame = tk.Frame(sbar, bg=self.BG2)
        self.scan_confirm_frame.pack(side="right", padx=8)
        self.scan_confirm_lbl = tk.Label(
            self.scan_confirm_frame, textvariable=self.scan_confirm_var,
            bg=self.BG2, fg="#ffcc66", font=("Segoe UI", 10, "bold"))
        self.scan_confirm_lbl.pack(side="left", padx=4)
        self.scan_ok_btn = tk.Button(
            self.scan_confirm_frame, text="\u2713", font=("Segoe UI", 10, "bold"),
            bg="#2a5a2a", fg="white", relief="flat", bd=0, padx=6,
            command=self._confirm_scan_accept)
        self.scan_no_btn = tk.Button(
            self.scan_confirm_frame, text="\u2717", font=("Segoe UI", 10, "bold"),
            bg="#5a2a2a", fg="white", relief="flat", bd=0, padx=6,
            command=self._confirm_scan_reject)

        self._update_ocr_status()

        # Card display + position
        disp = tk.Frame(self, bg=self.BG, pady=6)
        disp.pack(fill="x", padx=12)

        # Position badge
        self.pos_var = tk.StringVar(value="")
        self.pos_lbl = tk.Label(disp, textvariable=self.pos_var, bg="#333",
                                fg="#888", font=("Segoe UI", 16, "bold"),
                                width=4, relief="ridge", bd=2, pady=4)
        self.pos_lbl.pack(side="left", padx=(0, 10))

        # Hole cards
        hf = tk.Frame(disp, bg=self.BG)
        hf.pack(side="left")
        self.hole_lbls = []
        for _ in range(2):
            lbl = tk.Label(hf, text=" ? ", bg="#333", fg="#666",
                           font=("Consolas", 24, "bold"), width=3, relief="groove", bd=2)
            lbl.pack(side="left", padx=3)
            self.hole_lbls.append(lbl)
        self.hn_var = tk.StringVar(value="")
        tk.Label(hf, textvariable=self.hn_var, bg=self.BG, fg="#ccc",
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=8)

        # Board cards
        bf = tk.Frame(disp, bg=self.BG)
        bf.pack(side="left", padx=(10, 0))
        self.board_lbls = []
        for _ in range(5):
            lbl = tk.Label(bf, text="  ", bg="#222", fg="#666",
                           font=("Consolas", 24, "bold"), width=3, relief="groove", bd=2)
            lbl.pack(side="left", padx=3)
            self.board_lbls.append(lbl)

        # Quick card picker
        picker = tk.Frame(self, bg=self.BG2, pady=6)
        picker.pack(fill="x", padx=12, pady=(6, 0))

        rf = tk.Frame(picker, bg=self.BG2)
        rf.pack(fill="x")
        self.rank_btns = {}
        for r in RANKS:
            btn = tk.Button(rf, text=r, width=3, font=("Consolas", 14, "bold"),
                            bg="#2a3a2a", fg="white", activebackground="#4a6a4a",
                            relief="flat", bd=0, pady=4,
                            command=lambda rk=r: self._pick_rank(rk))
            btn.pack(side="left", padx=2, pady=2)
            self.rank_btns[r] = btn

        sf = tk.Frame(picker, bg=self.BG2)
        sf.pack(fill="x", pady=(4, 0))
        self.suit_btns = {}
        self.pending_lbl = tk.Label(sf, text="", bg=self.BG2, fg="#888",
                                     font=("Segoe UI", 13))
        self.pending_lbl.pack(side="left", padx=6)
        for s, clr, sym in SUITS:
            btn = tk.Button(sf, text=f" {sym} ", font=("Segoe UI", 18, "bold"),
                            bg="#222", fg=clr, activebackground="#444",
                            relief="flat", bd=0, padx=6, pady=2, state="disabled",
                            command=lambda su=s: self._pick_suit(su))
            btn.pack(side="left", padx=4)
            self.suit_btns[s] = btn

        tk.Button(sf, text="CLEAR", font=("Segoe UI", 12, "bold"),
                  bg="#5a2020", fg="white", activebackground="#803030",
                  relief="flat", bd=0, padx=12, pady=2,
                  command=self._clear_hole).pack(side="right", padx=6)

        # Texture
        self.texture_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.texture_var, bg=self.BG, fg="#77bbaa",
                 font=("Segoe UI", 11), pady=2).pack()

        # PREFLOP
        pf = tk.Frame(self, bg="#1a2e20")
        pf.pack(fill="x", padx=12, pady=4)
        tk.Label(pf, text="PREFLOP", bg="#1a2e20", fg="#88aaff",
                 font=("Segoe UI", 10, "bold"), padx=6).pack(anchor="w")
        self.pf_action_var = tk.StringVar(value="Pick cards...")
        self.pf_action_lbl = tk.Label(pf, textvariable=self.pf_action_var, bg="#1a2e20",
                                      fg="#888", font=("Segoe UI", 22, "bold"),
                                      wraplength=600, pady=4)
        self.pf_action_lbl.pack()
        self.pf_reason_var = tk.StringVar(value="")
        tk.Label(pf, textvariable=self.pf_reason_var, bg="#1a2e20", fg="#bbb",
                 font=("Segoe UI", 11), wraplength=600, pady=2, justify="center").pack()

        # POSTFLOP
        res = tk.Frame(self, bg=self.BG2)
        res.pack(fill="x", padx=12, pady=4)
        tk.Label(res, text="POSTFLOP", bg=self.BG2, fg="#ffaa44",
                 font=("Segoe UI", 10, "bold"), padx=6).pack(anchor="w")
        self.post_action_var = tk.StringVar(value="")
        self.post_action_lbl = tk.Label(res, textvariable=self.post_action_var, bg=self.BG2,
                                        fg=self.GOLD, font=("Segoe UI", 22, "bold"),
                                        wraplength=600, pady=4)
        self.post_action_lbl.pack()
        self.post_hand_var = tk.StringVar(value="")
        tk.Label(res, textvariable=self.post_hand_var, bg=self.BG2, fg="#aaddaa",
                 font=("Segoe UI", 12), pady=2).pack()
        # ── "ТИ ИМАШ / ТЕ БИЕ" поленце ──
        self.threats_frame = tk.Frame(res, bg="#1a1a22", bd=1, relief="solid")
        self.threats_frame.pack(fill="x", padx=20, pady=4)
        self.threats_have_var = tk.StringVar(value="")
        tk.Label(self.threats_frame, textvariable=self.threats_have_var,
                 bg="#1a1a22", fg="#88ddff",
                 font=("Segoe UI", 10, "bold"), anchor="w", padx=8, pady=2,
                 wraplength=600, justify="left").pack(fill="x")
        self.threats_beat_var = tk.StringVar(value="")
        tk.Label(self.threats_frame, textvariable=self.threats_beat_var,
                 bg="#1a1a22", fg="#ff9988",
                 font=("Segoe UI", 10), anchor="w", padx=8, pady=2,
                 wraplength=600, justify="left").pack(fill="x")
        self.post_reason_var = tk.StringVar(value="")
        tk.Label(res, textvariable=self.post_reason_var, bg=self.BG2, fg="#ccc",
                 font=("Segoe UI", 11), wraplength=600, pady=2, justify="center").pack()
        self.sizing_var = tk.StringVar(value="")
        tk.Label(res, textvariable=self.sizing_var, bg=self.BG2, fg="#ffcc66",
                 font=("Segoe UI", 11, "bold"), pady=2).pack()

    # ── Card Picker ───────────────────────────────────────────────────────────
    def _pick_rank(self, rank):
        if len(self.hole_cards) >= 2:
            return
        self.pending_rank = rank
        self.pending_lbl.config(text=f"{rank} ?", fg="#ddd")
        for r, btn in self.rank_btns.items():
            btn.config(bg="#5a8a40" if r == rank else "#2a3a2a")
        for s, btn in self.suit_btns.items():
            if (rank, s) in self.hole_cards:
                btn.config(state="disabled")
            else:
                btn.config(state="normal")

    def _pick_suit(self, suit):
        if self.pending_rank is None or len(self.hole_cards) >= 2:
            return
        card = (self.pending_rank, suit)
        self.hole_cards.append(card)
        self.pending_rank = None
        self.pending_lbl.config(text="")
        for btn in self.rank_btns.values():
            btn.config(bg="#2a3a2a")
        for btn in self.suit_btns.values():
            btn.config(state="disabled")
        self._update_display()
        if len(self.hole_cards) < 2:
            self.status_var.set("Pick 2nd card")
        elif len(self.hole_cards) == 2:
            # Correction tracking: ако имаме recent scan за текущата ръка,
            # записваме user-entered карти като ground truth (gold signal)
            if (poker_logger and self._last_scan_id is not None
                    and self._last_scan_hand_id == self.watcher.hand_id):
                try:
                    poker_logger.record_correction(
                        self._last_scan_id,
                        [list(c) for c in self.hole_cards],
                    )
                except Exception:
                    pass
            elif _LOG:
                _LOG.info("[UI] manual cards entered=%s hand=%s",
                          " ".join(f"{r}{s}" for r, s in self.hole_cards),
                          self.watcher.hand_id or "-")

    def _reset_picker(self):
        """Reset the card picker UI state (no redraw)."""
        self.hole_cards = []
        self.pending_rank = None
        self.pending_lbl.config(text="")
        for btn in self.rank_btns.values():
            btn.config(bg="#2a3a2a")
        for btn in self.suit_btns.values():
            btn.config(state="disabled")

    def _clear_hole(self):
        # Cancel pending auto-scan/retry за да не върне картите обратно
        if self._scan_after_id:
            try:
                self.after_cancel(self._scan_after_id)
            except Exception:
                pass
            self._scan_after_id = None
        # Dismiss pending confirm UI (ако има middle-conf scan)
        if self._pending_scan:
            self._confirm_scan_reject()
        # Маркирай текущата ръка като "сканирана" — fallback няма да retrigger-не
        # (user явно иска да въвежда ръчно на тази ръка)
        if self.watcher.hand_id:
            self._last_scanned_hand_id = self.watcher.hand_id
        self._scan_attempt = MAX_SCAN_ATTEMPTS  # deactivate retry
        self._reset_picker()
        self._update_display()
        self.status_var.set("Pick your cards")

    def _set_card_lbl(self, lbl, card, bg):
        if card:
            r, s = card
            lbl.config(text=f"{r}{SYM[s]}", fg=SCLR[s], bg=bg)
        else:
            lbl.config(text=" ? ", fg="#666", bg="#333")

    # ── Scanner ───────────────────────────────────────────────────────────────
    def _update_ocr_status(self):
        """Показва read-only статус на OCR backend-а (EasyOCR GPU/CPU или ✗)."""
        if not self.scanner or not self.scanner.available:
            self.ocr_status_var.set("")
            return
        self.ocr_status_var.set(self.scanner.ocr_status)

    def _on_toggle_autoscan(self):
        if not self.scanner or not self.scanner.available:
            self.auto_scan_var.set(False)
            return
        if self.auto_scan_var.get() and not self.scanner.is_calibrated:
            self.status_var.set("Калибрирай първо")
            self.auto_scan_var.set(False)
            self._calibrate_dialog()

    def _select_window_dialog(self, on_selected=None):
        """Показва list с всички видими windows и позволява избор на target."""
        if not self.scanner or not self.scanner.available:
            return
        windows = self.scanner.list_visible_windows()
        if not windows:
            self.status_var.set("Няма видими прозорци")
            return

        dlg = tk.Toplevel(self)
        dlg.title("Избери PokerStars масата")
        dlg.configure(bg=self.BG)
        dlg.transient(self)
        dlg.attributes('-topmost', True)
        dlg.geometry("680x420")

        tk.Label(dlg, bg=self.BG, fg="#ddd", font=("Segoe UI", 11),
                 justify="left", wraplength=640,
                 text=("Избери прозореца на ПОКЕР МАСАТА (не лобито).\n"
                       "Tip: търси \"Влязъл като <твоето име>\" или \"Холдем\" "
                       "в title-а.")).pack(padx=10, pady=8)

        # Listbox с всички windows
        frame = tk.Frame(dlg, bg=self.BG)
        frame.pack(fill="both", expand=True, padx=10, pady=4)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        lb = tk.Listbox(frame, font=("Consolas", 9),
                        bg="#0f1f14", fg="#ddd",
                        selectbackground="#4a6a4a", selectforeground="white",
                        yscrollcommand=scrollbar.set,
                        activestyle="none", bd=0, highlightthickness=0)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)

        # Подреди: приоритет на тези с "Влязъл като" / "Холдем" etc.
        default_keywords = ["Влязъл като", "Logged in as", "Холдем",
                            "Hold'em", "Holdem", "Mercury"]

        def score(title: str) -> int:
            tl = title.lower()
            for kw in default_keywords:
                if kw.lower() in tl:
                    return 0  # приоритет
            return 1

        windows_sorted = sorted(windows, key=lambda tw: (score(tw[0]), tw[0]))

        for title, _ in windows_sorted:
            display = title if len(title) <= 100 else title[:97] + "..."
            lb.insert("end", display)

        # Pre-select top candidate
        if windows_sorted:
            lb.selection_set(0)
            lb.activate(0)

        status = tk.StringVar(value="")
        tk.Label(dlg, textvariable=status, bg=self.BG, fg="#ffcc66",
                 font=("Segoe UI", 10)).pack(pady=2)

        def pick():
            sel = lb.curselection()
            if not sel:
                status.set("Избери ред от списъка.")
                return
            idx = sel[0]
            title = windows_sorted[idx][0]
            self.scanner.set_target_window(title)
            self.status_var.set(f"\u2713 Избран: {title[:40]}...")
            dlg.destroy()
            if on_selected:
                on_selected()

        def cancel():
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=self.BG)
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="Избери този", command=pick,
                  bg="#2a5a2a", fg="white", activebackground="#3a7a3a",
                  relief="flat", bd=0, padx=14, pady=6,
                  font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)
        tk.Button(btn_row, text="Откажи", command=cancel,
                  bg="#5a2020", fg="white", activebackground="#7a3030",
                  relief="flat", bd=0, padx=14, pady=6,
                  font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)
        lb.bind("<Double-Button-1>", lambda e: pick())
        dlg.protocol("WM_DELETE_WINDOW", cancel)

    def _calibrate_dialog(self):
        if not self.scanner or not self.scanner.available:
            return
        win = self.scanner.find_ps_window()
        if win is None:
            # Няма auto-match → покажи window selector
            self._select_window_dialog(on_selected=lambda: self._calibrate_dialog())
            return
        rect = self.scanner.window_rect(win)
        if rect is None:
            self.status_var.set("Не мога да прочета размерите на PS")
            return

        dlg = tk.Toplevel(self)
        dlg.title("Калибриране на hole карти")
        dlg.configure(bg=self.BG)
        dlg.transient(self)
        dlg.attributes('-topmost', True)
        dlg.geometry("460x340")

        # Показваме текущата калибрация, ако съществува (рекалибриране)
        already = self.scanner.is_calibrated
        if already:
            cal = self.scanner.calibration or {}
            cur = (f"Текуща: c1=({cal.get('card1_x_ratio',0):.3f},"
                   f"{cal.get('card1_y_ratio',0):.3f})  w/h="
                   f"{cal.get('card_w_ratio',0):.3f}/{cal.get('card_h_ratio',0):.3f}")
            tk.Label(dlg, text="\u21BB РЕКАЛИБРИРАНЕ", bg=self.BG, fg="#ffcc66",
                     font=("Segoe UI", 11, "bold")).pack(pady=(8, 0))
            tk.Label(dlg, text=cur, bg=self.BG, fg="#888",
                     font=("Consolas", 9)).pack()

        info = tk.Label(
            dlg, bg=self.BG, fg="#ddd", font=("Segoe UI", 10), justify="left",
            text=("Увери се, че си на маса С КАРТИ В РЪКАТА.\n\n"
                  "\U0001F446 DRAG с МИШКАТА правоъгълник, който покрива\n"
                  "rank ъгълчетата на двете карти заедно:\n\n"
                  "• Натисни ляв бутон ТОЧНО НАД rank-а на 1-вата карта\n"
                  "• Влачи (без да пускаш) ДО ПОД suit символа на 2-рата\n"
                  "• Пусни бутона\n\n"
                  "Червен правоъгълник показва какво маркираш. Анимациите\n"
                  "не пречат — фиксира се при release.\n\n"
                  "НЕ маркирай цялата карта, само малкото ъгълче с rank+suit!"),
        )
        info.pack(padx=14, pady=8)

        state = {"click1": None, "click2": None, "done": False}
        status = tk.StringVar(value="\u23F3 Натисни ЛЯВ БУТОН над rank-а на 1-вата карта и влачи...")
        tk.Label(dlg, textvariable=status, bg=self.BG, fg="#ffcc66",
                 font=("Segoe UI", 10, "bold"), wraplength=420,
                 justify="center").pack(pady=4)

        clicks_var = tk.StringVar(value="клик 1: —    клик 2: —")
        tk.Label(dlg, textvariable=clicks_var, bg=self.BG, fg="#88bbaa",
                 font=("Consolas", 9)).pack(pady=2)

        # ctypes mouse polling
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            user32 = ctypes.windll.user32

            def get_cursor_pos():
                pt = POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                return (pt.x, pt.y)

            def is_left_pressed():
                return bool(user32.GetAsyncKeyState(0x01) & 0x8000)

        except Exception:
            status.set("Error: ctypes unavailable")
            return

        poll_state = {"prev_pressed": True, "cancelled": False}

        def refresh_clicks_display():
            c1 = state["click1"]; c2 = state["click2"]
            s1 = f"{c1}" if c1 else "—"
            s2 = f"{c2}" if c2 else "—"
            clicks_var.set(f"клик 1: {s1}    клик 2: {s2}")

        def restart():
            state["click1"] = None
            state["click2"] = None
            state["done"] = False
            status.set("\u23F3 Натисни ЛЯВ БУТОН над rank-а на 1-вата карта и влачи...")
            refresh_clicks_display()

        def cancel():
            poll_state["cancelled"] = True
            dlg.destroy()

        # Показва кой прозорец е избран (за да знае юзърът)
        win_title = ""
        try:
            win_title = (win.title or "")[:60]
        except Exception:
            pass
        tk.Label(dlg, text=f"\U0001F3AF Target: {win_title}", bg=self.BG,
                 fg="#88bbff", font=("Consolas", 9),
                 wraplength=420).pack(pady=2)

        def change_window():
            cancel()
            self._select_window_dialog(on_selected=lambda: self._calibrate_dialog())

        btn_row = tk.Frame(dlg, bg=self.BG)
        btn_row.pack(pady=10)
        tk.Button(btn_row, text="\u21BB Отначало", command=restart,
                  bg="#2a4a6a", fg="white", activebackground="#3a6a8a",
                  relief="flat", bd=0, padx=10, pady=4,
                  font=("Segoe UI", 10, "bold")).pack(side="left", padx=4)
        tk.Button(btn_row, text="Друг прозорец", command=change_window,
                  bg="#4a3a6a", fg="white", activebackground="#6a5a8a",
                  relief="flat", bd=0, padx=10, pady=4,
                  font=("Segoe UI", 10, "bold")).pack(side="left", padx=4)
        tk.Button(btn_row, text="Затвори", command=cancel,
                  bg="#5a2020", fg="white", activebackground="#7a3030",
                  relief="flat", bd=0, padx=10, pady=4,
                  font=("Segoe UI", 10, "bold")).pack(side="left", padx=4)
        dlg.protocol("WM_DELETE_WINDOW", cancel)

        # ---- Визуален overlay за drag rectangle ----
        try:
            overlay = tk.Toplevel(dlg)
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            overlay.attributes("-transparentcolor", "black")
            overlay.config(bg="black")
            ov_canvas = tk.Canvas(overlay, bg="black",
                                  highlightthickness=0, bd=0)
            ov_canvas.pack(fill="both", expand=True)
            overlay.withdraw()
        except Exception:
            overlay = None
            ov_canvas = None

        def show_overlay(x1, y1, x2, y2):
            if overlay is None:
                return
            ox = min(x1, x2); oy = min(y1, y2)
            ow = abs(x2 - x1); oh = abs(y2 - y1)
            if ow < 2 or oh < 2:
                overlay.withdraw()
                return
            try:
                overlay.geometry(f"{ow}x{oh}+{ox}+{oy}")
                ov_canvas.delete("all")
                # Червен frame + полупрозрачна вътрешност
                ov_canvas.create_rectangle(0, 0, ow, oh,
                                           outline="#ff3030", width=2,
                                           fill="")
                overlay.deiconify()
            except Exception:
                pass

        def hide_overlay():
            if overlay is None:
                return
            try:
                overlay.withdraw()
            except Exception:
                pass

        # drag_state: None | {"start": (x,y)}
        drag_state = {"start": None}

        def poll_click():
            if poll_state["cancelled"]:
                hide_overlay()
                return
            # Ако сме приключили, спираме да чакаме нови кликове
            if state["done"]:
                dlg.after(DIALOG_POLL_MS, poll_click)
                return
            pressed = is_left_pressed()
            pos = get_cursor_pos()

            # Dialog bounds (за ignore)
            try:
                dlg_l = dlg.winfo_rootx(); dlg_t = dlg.winfo_rooty()
                dlg_r = dlg_l + dlg.winfo_width()
                dlg_b = dlg_t + dlg.winfo_height()
                on_dialog = (dlg_l <= pos[0] <= dlg_r and
                             dlg_t <= pos[1] <= dlg_b)
            except Exception:
                on_dialog = False

            l, t, w, h = rect
            inside = (l <= pos[0] <= l + w and t <= pos[1] <= t + h)

            # --- Edge: press START ---
            if not poll_state["prev_pressed"] and pressed:
                if on_dialog:
                    pass  # игнорирай — клик върху dialog
                elif not inside:
                    status.set(f"\u26A0 Започна drag извън PokerStars ({pos}).")
                else:
                    drag_state["start"] = pos
                    status.set("\U0001F446 Drag-ни до противоположния ъгъл "
                               "(под suit символа на 2-рата карта)...")

            # --- По време на drag ---
            if drag_state["start"] is not None and pressed:
                x1, y1 = drag_state["start"]
                x2, y2 = pos
                show_overlay(x1, y1, x2, y2)
                dw = abs(x2 - x1); dh = abs(y2 - y1)
                clicks_var.set(f"drag: {drag_state['start']} \u2192 {pos}  "
                               f"({dw}\u00d7{dh})")

            # --- Edge: RELEASE ---
            if poll_state["prev_pressed"] and not pressed and drag_state["start"] is not None:
                click1 = drag_state["start"]
                click2 = pos
                drag_state["start"] = None
                hide_overlay()

                # Normalize: click1 = top-left, click2 = bottom-right
                x1 = min(click1[0], click2[0]); y1 = min(click1[1], click2[1])
                x2 = max(click1[0], click2[0]); y2 = max(click1[1], click2[1])
                norm1 = (x1, y1); norm2 = (x2, y2)

                # Валидация — правоъгълникът трябва да е в PS
                end_inside = (l <= x2 <= l + w and t <= y2 <= t + h)
                if not end_inside:
                    status.set(f"\u26A0 Drag-ът завърши извън PokerStars. "
                               f"Натисни 'Отначало'.")
                elif (x2 - x1) < 10 or (y2 - y1) < 5:
                    status.set(f"\u26A0 Правоъгълникът е твърде малък "
                               f"({x2-x1}\u00d7{y2-y1}px). Опитай пак.")
                else:
                    state["click1"] = norm1
                    state["click2"] = norm2
                    refresh_clicks_display()
                    ok = self.scanner.calibrate_from_clicks(
                        rect, norm1, norm2)
                    if ok:
                        self.status_var.set("\u2713 Калибрирано")
                        status.set(f"\u2713 КАЛИБРИРАНО! "
                                   f"{x2-x1}\u00d7{y2-y1}px. "
                                   "Ако не е точно → 'Отначало'.")
                        state["done"] = True
                    else:
                        status.set("\u26A0 Грешна калибрация. "
                                   "Натисни 'Отначало' и опитай пак.")

            poll_state["prev_pressed"] = pressed
            dlg.after(CALIBRATE_POLL_MS, poll_click)

        # Override restart/cancel да скриват overlay
        _orig_restart = restart
        def restart_with_overlay():
            drag_state["start"] = None
            hide_overlay()
            _orig_restart()
        # Закачаме към бутона "Отначало"
        for child in btn_row.winfo_children():
            try:
                if isinstance(child, tk.Button) and "Отначало" in child.cget("text"):
                    child.config(command=restart_with_overlay)
            except Exception:
                pass

        _orig_cancel = cancel
        def cancel_with_overlay():
            hide_overlay()
            try:
                if overlay is not None:
                    overlay.destroy()
            except Exception:
                pass
            _orig_cancel()
        dlg.protocol("WM_DELETE_WINDOW", cancel_with_overlay)
        for child in btn_row.winfo_children():
            try:
                if isinstance(child, tk.Button) and "Затвори" in child.cget("text"):
                    child.config(command=cancel_with_overlay)
            except Exception:
                pass

        dlg.after(200, poll_click)

    def _maybe_autoscan(self):
        """Извиква се след new_hand ако auto-scan е ON."""
        if not self.scanner or not self.scanner.available:
            self.status_var.set("Auto-scan skip: scanner unavailable")
            return
        if not self.auto_scan_var.get():
            return  # silently skip когато checkbox-а е OFF
        if not self.scanner.is_calibrated:
            self.status_var.set("Auto-scan skip: не е калибриран")
            return
        if self.hole_cards:
            self.status_var.set("Auto-scan skip: карти вече въведени")
            return
        # Schedule scan след delay. Маркираме hand_id ВЕДНАГА — така че
        # _maybe_autoscan_fallback няма да re-trigger-не докато чакаме.
        delay = int(self.scanner.config.get("scan_delay_ms", 500))
        if self._scan_after_id:
            try: self.after_cancel(self._scan_after_id)
            except Exception: pass
        if self.watcher.hand_id:
            self._last_scanned_hand_id = self.watcher.hand_id
        self.status_var.set(f"Auto-scan след {delay}ms...")
        self._scan_after_id = self.after(delay, self._auto_scan)
        # Auto-detect dealer button с малко по-голям delay (D чипът обикновено
        # се анимира заедно с картите). При успех overwrite-ва hero_position
        # само ако log-а не е locked.
        btn_delay = delay + 200
        self.after(btn_delay, lambda: self._scan_dealer_button(auto=True))

    def _auto_scan(self, manual_trigger=False):
        """Scheduler + producer: стартира scan в background thread.

        Scanner.scan() може да отнеме 1-3s (EasyOCR) → ако го извикаме
        директно, Tkinter UI freezes. Правим scan в worker thread, а
        result-а се post-ва обратно на UI thread чрез self.after(0, ...).
        """
        self._scan_after_id = None
        if self.hole_cards and not manual_trigger:
            return
        if not self.scanner or not self.scanner.available:
            self.status_var.set("Scanner недостъпен")
            return
        if not self.scanner.is_calibrated:
            self.status_var.set("Не е калибриран")
            return
        if self._scan_in_progress:
            return  # вече има scan в полет — не дублирай
        win = self.scanner.find_ps_window()
        if win is None:
            self.status_var.set("PokerStars прозорец не намерен")
            if _LOG:
                _LOG.warning("[SCAN] aborted: PS window не намерен")
            return
        self._scan_in_progress = True
        self._scan_attempt += 1
        attempt_str = (f" ({self._scan_attempt}/{MAX_SCAN_ATTEMPTS})"
                       if self._scan_attempt > 1 else "")
        self.status_var.set(f"\U0001F50D Сканиране{attempt_str}...")
        t0 = time.monotonic()
        hand_id_at_start = self.watcher.hand_id

        def worker():
            err = None
            result = None
            try:
                result = self.scanner.scan(win)
            except Exception as e:
                err = str(e)
                if _LOG:
                    _LOG.error("[SCAN] exception: %s", e, exc_info=True)
            # Post back to UI thread (thread-safe)
            self.after(0, lambda: self._on_scan_complete(
                result, err, t0, manual_trigger, win, hand_id_at_start,
            ))

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_complete(self, result, err, t0, manual_trigger, win,
                          hand_id_at_start):
        """UI-thread handler за scan резултата. Викат го чрез self.after(0)."""
        self._scan_in_progress = False
        duration_ms = int((time.monotonic() - t0) * 1000)

        # Ако ръката се е сменила докато сме сканирали → drop (stale result)
        if (hand_id_at_start and self.watcher.hand_id
                and hand_id_at_start != self.watcher.hand_id):
            if _LOG:
                _LOG.info("[SCAN] dropped stale result (hand changed %s→%s)",
                          hand_id_at_start, self.watcher.hand_id)
            return

        # Ако юзърът е въвел ръчно по време на scan → drop (освен manual_trigger)
        if self.hole_cards and not manual_trigger:
            return

        # Error path
        if err is not None:
            self.status_var.set(f"Scan error: {err[:40]}")
            if poker_logger:
                poker_logger.record_scan({
                    "hand_id": hand_id_at_start,
                    "window_title": getattr(win, "title", None),
                    "duration_ms": duration_ms,
                    "calibrated": self.scanner.is_calibrated,
                    "easyocr": self.scanner.easyocr_enabled,
                    "tesseract": self.scanner.ocr_enabled,
                    "outcome": "error", "error": err,
                })
            return
        if result is None:
            # Обикновено се случва когато картите са още в анимация.
            # Retry със escalating delay — ако не сме превишили max attempts
            # И все още сме на същата ръка И auto-scan е ON.
            if (not manual_trigger
                    and self._scan_attempt < MAX_SCAN_ATTEMPTS
                    and self.auto_scan_var.get()
                    and self.watcher.hand_id == hand_id_at_start):
                retry_idx = self._scan_attempt - 1  # 0-based в SCAN_RETRY_DELAYS_MS
                if 0 <= retry_idx < len(SCAN_RETRY_DELAYS_MS):
                    next_delay = SCAN_RETRY_DELAYS_MS[retry_idx]
                    self.status_var.set(
                        f"Scan retry {self._scan_attempt + 1}/"
                        f"{MAX_SCAN_ATTEMPTS} след {next_delay}ms...")
                    if _LOG:
                        _LOG.info("[SCAN] retry %d/%d after %dms (hand=%s)",
                                  self._scan_attempt + 1, MAX_SCAN_ATTEMPTS,
                                  next_delay, hand_id_at_start)
                    self._scan_after_id = self.after(
                        next_delay, self._auto_scan)
                    return
            self.status_var.set("Scan: няма резултат (картите още в анимация?)")
            if _LOG:
                _LOG.warning("[SCAN] returned None after %d attempts (hand=%s)",
                             self._scan_attempt, hand_id_at_start)
            return

        cards = result["cards"]
        conf = result["confidence"]
        r1, s1 = cards[0]; r2, s2 = cards[1]
        det_str = f"{r1}{SYM[s1]} {r2}{SYM[s2]}"
        auto_thr = float(self.scanner.config.get("auto_confirm_threshold", 0.85))
        conf_thr = float(self.scanner.config.get("confirm_threshold", 0.50))

        # Регистрирай scan record (outcome-ът се update-ва по-долу)
        scan_id = None
        if poker_logger:
            try:
                win_rect = self.scanner.window_rect(win)
            except Exception:
                win_rect = None
            scan_id = poker_logger.record_scan({
                "hand_id": hand_id_at_start,
                "window_title": getattr(win, "title", None),
                "window_rect": list(win_rect) if win_rect else None,
                "duration_ms": duration_ms,
                "cards": [list(c) for c in cards],
                "confidence": conf,
                "details": [list(d) for d in result.get("details", [])],
                "detectors": list(result.get("detectors", [])),
                "calibrated": self.scanner.is_calibrated,
                "easyocr": result.get("easyocr_available"),
                "tesseract": result.get("tesseract_ok"),
                "outcome": "pending",
            })
            self._last_scan_id = scan_id
            self._last_scan_hand_id = hand_id_at_start

        if conf >= auto_thr:
            if manual_trigger:
                self.hole_cards = []
            self.hole_cards = list(cards)
            self._update_display()
            self.status_var.set(
                f"\U0001F50D {det_str} ({int(conf*100)}% • {duration_ms}ms)")
            self._last_scanned_hand_id = hand_id_at_start
            if poker_logger and scan_id is not None:
                poker_logger.update_scan_outcome(scan_id, "auto_accepted")
        elif conf >= conf_thr:
            self._pending_scan = result
            details = result.get("details", [])
            if details and len(details) == 2:
                d1, d2 = details
                self.scan_confirm_var.set(
                    f"?: {d1[0]}{SYM.get(d1[2],'?')}"
                    f"(r{int(d1[1]*100)}/s{int(d1[3]*100)}) "
                    f"{d2[0]}{SYM.get(d2[2],'?')}"
                    f"(r{int(d2[1]*100)}/s{int(d2[3]*100)})"
                )
            else:
                self.scan_confirm_var.set(f"?: {det_str} ({int(conf*100)}%)")
            self.scan_ok_btn.pack(side="left", padx=2)
            self.scan_no_btn.pack(side="left", padx=2)
            if self._confirm_after_id:
                try: self.after_cancel(self._confirm_after_id)
                except Exception: pass
            self._confirm_after_id = self.after(
                SCAN_CONFIRM_TIMEOUT_MS, self._confirm_scan_reject)
        else:
            details = result.get("details", [])
            if details and len(details) == 2:
                d1, d2 = details
                dbg = (f"Scan low: {d1[0]}{SYM.get(d1[2],'?')}"
                       f"({int(d1[1]*100)}/{int(d1[3]*100)}) "
                       f"{d2[0]}{SYM.get(d2[2],'?')}"
                       f"({int(d2[1]*100)}/{int(d2[3]*100)})")
            else:
                dbg = f"Scan low: {det_str} ({int(conf*100)}%)"
            self.status_var.set(dbg)
            if poker_logger and scan_id is not None:
                poker_logger.update_scan_outcome(scan_id, "low_conf_fallback")

    def _manual_scan(self):
        """Явно поискан scan от юзъра (бутон Scan now)."""
        self._auto_scan(manual_trigger=True)

    def _scan_dealer_button(self, auto=False):
        """Screenshot-based detection на D чипа → извежда hero position.

        Ако auto=True и confidence е висока → overwrite-ва
        self.watcher.hero_position и заключва position.
        При ниска confidence или manual mode — само показва в status.
        """
        if not self.scanner or not self.scanner.available:
            if not auto:
                self.status_var.set("Scanner недостъпен")
            return None
        win = self.scanner.find_ps_window()
        if win is None:
            if not auto:
                self.status_var.set("PS прозорец не намерен")
            return None
        # При manual click → пиши debug файлове
        debug_dir = None
        if not auto:
            import tempfile, time
            ts = time.strftime("%H%M%S")
            debug_dir = Path(tempfile.gettempdir()) / f"poker_btn_{ts}"
        try:
            det = self.scanner.detect_dealer_button(win, debug_dir=debug_dir)
        except Exception as e:
            if not auto:
                self.status_var.set(f"D scan error: {e}")
            return None
        if det is None:
            if not auto:
                self.status_var.set("D чипът не е намерен")
            return None
        n = (self.watcher.num_players
             or self.watcher._view_num_players or 6)
        pos, slot, ang, err = position_from_dealer_ratio(
            det["x_ratio"], det["y_ratio"], n,
        )
        msg = (f"D→{pos} (slot {slot}, ang={ang:.0f}°, "
               f"err={err:.0f}°, conf={det['confidence']:.2f})")
        if not auto:
            self.status_var.set(msg)
            if debug_dir and debug_dir.exists():
                try:
                    lines = [
                        "=== DEALER BUTTON DETECTION ===",
                        f"window_title:   {win.title!r}",
                        f"window_rect:    {self.scanner.window_rect(win)}",
                        f"num_players:    {n} (watcher={self.watcher.num_players}, view={self.watcher._view_num_players})",
                        f"log_position:   {self.watcher.hero_position} (locked={self.watcher._position_locked})",
                        f"hough_total:    {det.get('hough_total', '?')}",
                        f"rejected:       {det.get('rejected_count', '?')}",
                        f"passed_count:   {len(det.get('candidates', []))}",
                        "",
                        "=== WINNER ===",
                        msg,
                        f"x={det['x_ratio']:.4f} y={det['y_ratio']:.4f} "
                        f"r={det['radius_px']} "
                        f"bright={det['brightness']:.1f} "
                        f"red={det['red_ratio']*100:.1f}%",
                        "",
                    ]
                    cands = det.get("candidates") or []
                    if cands:
                        lines.append("=== ALL PASSED CANDIDATES "
                                     "(sorted by score) ===")
                        lines.append(
                            f"{'#':>2} {'x%':>6} {'y%':>6} {'r':>3} "
                            f"{'bright':>7} {'red%':>6} {'score':>6} "
                            f"{'→hero':>7} {'slot':>5} {'ang':>6} {'err':>5}"
                        )
                        for i, ca in enumerate(cands):
                            p2, s2, a2, e2 = position_from_dealer_ratio(
                                ca["x_ratio"], ca["y_ratio"], n,
                            )
                            mark = "★" if i == 0 else ""
                            lines.append(
                                f"{i:>2d} "
                                f"{ca['x_ratio']*100:>5.1f}% "
                                f"{ca['y_ratio']*100:>5.1f}% "
                                f"{ca['r']:>3d} "
                                f"{ca['brightness']:>7.1f} "
                                f"{ca['red_ratio']*100:>5.1f}% "
                                f"{ca.get('score',0):>6.3f} "
                                f"{p2:>6s}{mark} "
                                f"{s2:>5d} "
                                f"{a2:>+5.0f}° "
                                f"{e2:>4.0f}°"
                            )
                        lines.append("")
                    lines.append("ℹ Виж и: candidates.txt (rejected detail) "
                                 "+ dealer_annotated.png (visual)")
                    (debug_dir / "btn.txt").write_text(
                        "\n".join(lines), encoding="utf-8")
                    os.startfile(str(debug_dir))
                except Exception as e:
                    print(f"btn.txt write error: {e}")
        # Auto-apply само ако имаме разумен ъгъл и вече имаме хора
        if auto and pos != '?' and err < 25 and det["confidence"] > 0.3:
            self.watcher.hero_position = pos
            self.watcher._position_locked = True
            self.watcher.num_players = n
        return {"pos": pos, "slot": slot, "angle": ang,
                "err": err, "det": det}

    def _debug_scan(self):
        """Запазва screenshot + crops + scan result за troubleshooting."""
        if not self.scanner or not self.scanner.available:
            self.status_var.set("Scanner недостъпен")
            return
        import tempfile, time, json
        ts = time.strftime("%H%M%S")
        outdir = Path(tempfile.gettempdir()) / f"poker_scan_debug_{ts}"
        outdir.mkdir(exist_ok=True)
        lines = []
        win = self.scanner.find_ps_window()
        if win is None:
            self.status_var.set("Debug: PS прозорец не намерен")
            return
        try:
            lines.append(f"window_title: {win.title!r}")
            lines.append(f"window_rect:  {self.scanner.window_rect(win)}")
            lines.append(f"calibrated:   {self.scanner.is_calibrated}")
            lines.append(f"calibration:  {self.scanner.calibration}")
            import poker_scanner as _ps
            lines.append(f"easyocr:      {_ps.EASYOCR_AVAILABLE}")
            lines.append(f"tesseract:    {_ps.TESSERACT_OK}")
            lines.append(f"gpu:          {_ps._GPU_AVAILABLE}")
            full = self.scanner.capture_window(win)
            if full:
                full.save(outdir / "window.png")
                lines.append(f"window.png:   {full.size}")
            pair = self.scanner.capture_hole_region(win)
            if pair:
                pair[0].save(outdir / "card1.png")
                pair[1].save(outdir / "card2.png")
                lines.append(f"card1/2.png:  {pair[0].size}")
                # Per-card диагностика — за да видим кой точно fail-ва при scan=None
                for i, img in enumerate(pair, 1):
                    try:
                        r, rc = self.scanner.detect_rank(img)
                        s, sc = self.scanner.detect_suit(img)
                        lines.append(f"card{i}: rank={r!r} (conf={rc:.2f}), suit={s!r} (conf={sc:.2f})")
                    except Exception as e:
                        lines.append(f"card{i}: ERROR {e}")
            result = self.scanner.scan(win)
            lines.append(f"scan_result:  {result}")
        except Exception as e:
            lines.append(f"ERROR: {e}")
        (outdir / "debug.txt").write_text("\n".join(lines), encoding="utf-8")
        # Отвори папката в Explorer
        try:
            os.startfile(str(outdir))
        except Exception:
            pass
        self.status_var.set(f"Debug: {outdir}")

    def _confirm_scan_accept(self):
        if self._confirm_after_id:
            try: self.after_cancel(self._confirm_after_id)
            except Exception: pass
            self._confirm_after_id = None
        pend = self._pending_scan
        self._pending_scan = None
        self.scan_confirm_var.set("")
        self.scan_ok_btn.pack_forget()
        self.scan_no_btn.pack_forget()
        if pend and not self.hole_cards:
            self.hole_cards = list(pend["cards"])
            self._update_display()
            self._last_scanned_hand_id = self.watcher.hand_id
            if poker_logger and self._last_scan_id is not None:
                poker_logger.update_scan_outcome(
                    self._last_scan_id, "confirm_accepted")

    def _confirm_scan_reject(self):
        if self._confirm_after_id:
            try: self.after_cancel(self._confirm_after_id)
            except Exception: pass
            self._confirm_after_id = None
        self._pending_scan = None
        self.scan_confirm_var.set("")
        self.scan_ok_btn.pack_forget()
        self.scan_no_btn.pack_forget()
        self.status_var.set("Ръчно избери картите")
        if poker_logger and self._last_scan_id is not None:
            poker_logger.update_scan_outcome(
                self._last_scan_id, "confirm_rejected")

    # ── Polling ───────────────────────────────────────────────────────────────
    def _poll(self):
        try:
            changed = self.watcher.poll()
            if self.watcher.new_hand:
                if _LOG:
                    _LOG.info("[HAND] new hand id=%s pos=%s players=%s",
                              self.watcher.hand_id or "-",
                              self.watcher.hero_position or "?",
                              self.watcher.num_players or "?")
                # Flush scans от предишната ръка (ако има pending)
                # — това ги записва в scans.jsonl
                if poker_logger and self._last_scan_hand_id:
                    try:
                        poker_logger.flush_hand(self._last_scan_hand_id)
                    except Exception:
                        pass
                # Strategy log: затвори предишна ръка + отвори нова
                if self.strategy_logger and self.watcher.hand_id:
                    try:
                        prev_hid = getattr(self, "_prev_hand_id", None)
                        if prev_hid and prev_hid != self.watcher.hand_id:
                            self.strategy_logger.log_hand_end(prev_hid)
                        self.strategy_logger.log_hand_start(
                            self.watcher.hand_id)
                        self._prev_hand_id = self.watcher.hand_id
                    except Exception:
                        pass
                self._reset_picker()  # auto-clear on new hand
                self._scan_attempt = 0  # reset retry counter за новата ръка
                # Clear pending scan UI от предишна ръка
                if self._pending_scan:
                    self._confirm_scan_reject()
                self._maybe_autoscan()
                changed = True
            else:
                # Fallback: ако auto-scan е ON и още не сме сканирали тази ръка
                # (напр. advisor стартира mid-hand, или потребителят току-що
                # включи auto-scan след като ръката е започнала).
                self._maybe_autoscan_fallback()
            # Strategy log: hero action (ако имаме нов)
            if (self.strategy_logger and self.watcher.hero_action_new
                    and self.watcher.hand_id):
                a = self.watcher.last_hero_action
                if a:
                    try:
                        self.strategy_logger.log_action(
                            self.watcher.hand_id,
                            a.get("code", ""),
                            a.get("amount", 0),
                            a.get("seq"),
                        )
                    except Exception:
                        pass
                self.watcher.hero_action_new = False
            if changed:
                self._update_display()
        except Exception as e:
            self.status_var.set(f"Error: {str(e)[:60]}")
            if _LOG:
                _LOG.error("[ERROR] poll exception: %s", e, exc_info=True)
        self.after(POLL_INTERVAL_MS, self._poll)

    def _maybe_autoscan_fallback(self):
        """Trigger auto-scan ако hand_id е различен от последно сканираното
        AND имаме auto-scan ON AND hole_cards е празно AND scanner is ready."""
        if not self.scanner or not self.scanner.available:
            return
        if not self.auto_scan_var.get():
            return
        if not self.scanner.is_calibrated:
            return
        if self.hole_cards:
            return
        hid = self.watcher.hand_id
        if not hid:
            return
        if hid == self._last_scanned_hand_id:
            return  # already scanned this hand
        if self._scan_after_id or self._pending_scan:
            return  # scan already scheduled/pending
        # Trigger scan scheduler (same as _maybe_autoscan path)
        self._maybe_autoscan()

    # ── Display ───────────────────────────────────────────────────────────────
    def _update_display(self):
        w = self.watcher
        hole = self.hole_cards
        board = w.board
        pos = w.hero_position
        n_players = w.num_players

        # Format call amount for display
        bb = w.bb_size if w.bb_size > 0 else 20000
        call_bb = w.call_amount / bb if bb > 0 else 0

        # Status line
        parts = []
        if w.hand_id:
            parts.append(f"#{w.hand_id[-6:]}")
        if n_players:
            alive = len(w.occupied_seats) - len(w.folded_seats)
            parts.append(f"{alive}/{n_players}p")
        if pos:
            parts.append(pos)
        if w.street != 'preflop':
            parts.append(w.street.upper())
        if w.facing_bet:
            parts.append(f"FACING {'RAISE' if w.facing_raise_preflop and w.street=='preflop' else 'BET'} ({call_bb:.1f}BB)")
        elif w.can_check:
            parts.append("CHECK option")
        elif w.new_hand:
            parts.append("NEW HAND!")
        self.status_var.set(" | ".join(parts) if parts else "Waiting...")

        # Position badge
        if pos:
            clr = self.POS_COLORS.get(pos, '#888')
            self.pos_var.set(pos)
            self.pos_lbl.config(fg=clr, bg="#1a1a1a")
        else:
            self.pos_var.set("--")
            self.pos_lbl.config(fg="#555", bg="#333")

        # Hole cards
        for i, lbl in enumerate(self.hole_lbls):
            if i < len(hole):
                self._set_card_lbl(lbl, hole[i], self.CARD_BG)
            else:
                self._set_card_lbl(lbl, None, "#333")
        self.hn_var.set(hand_name(hole[0], hole[1]) if len(hole) == 2 else "")

        # Board cards
        for i, lbl in enumerate(self.board_lbls):
            if i < len(board):
                self._set_card_lbl(lbl, board[i], "#60d0ff")
            else:
                self._set_card_lbl(lbl, None, "#222")

        # Texture
        if len(board) >= 3:
            self.texture_var.set(" \u00b7 ".join(texture_tags(board_info(board))))
        else:
            self.texture_var.set("")

        # ── PREFLOP ──────────────────────────────────────────────────────────
        if len(hole) == 2:
            facing_raise = w.facing_raise_preflop or (w.street == 'preflop' and w.facing_bet and call_bb > 1.5)
            pf = preflop_analyze(hole, hero_pos=pos, facing_raise=facing_raise)
            action_text = pf["action"]
            if facing_raise:
                # Показвай BB sizing само ако сме още preflop; на postflop street
                # call_amount не е preflop raise sizing — не подвеждай.
                if w.street == 'preflop' and call_bb > 0:
                    action_text = f"[vs RAISE {call_bb:.1f}BB] {action_text}"
                else:
                    action_text = f"[vs RAISE] {action_text}"
            self.pf_action_var.set(action_text)
            self.pf_reason_var.set(pf["reason"])
            self.pf_action_lbl.config(fg=pf["color"])
            # Strategy log: preflop advice
            if self.strategy_logger and w.hand_id:
                try:
                    bb_for_log = w.bb_size if w.bb_size > 0 else 0
                    stack_bb_pf = (w.hero_stack_chips / bb_for_log
                                   if bb_for_log > 0 and w.hero_stack_chips > 0
                                   else None)
                    self.strategy_logger.log_advice(
                        w.hand_id, 'preflop', pos, hole, [],
                        bool(facing_raise), None, stack_bb_pf,
                        max(1, (len(w.occupied_seats) - len(w.folded_seats)) - 1),
                        pf,
                    )
                except Exception:
                    pass
        else:
            self.pf_action_var.set("Pick cards..." if not hole else "Pick 2nd")
            self.pf_reason_var.set("")
            self.pf_action_lbl.config(fg="#888")

        # ── POSTFLOP ──────────────────────────────────────────────────────────
        if len(hole) == 2 and len(board) >= 3:
            all_c = list(hole) + board
            if len(set(all_c)) == 2 + len(board):
                facing = w.facing_bet and w.street != 'preflop'
                # HU heads-up: ако имаме позиция и са останали 2 играча — най-често е BB vs (PFR)
                vp = None
                alive = len(w.occupied_seats) - len(w.folded_seats)
                if alive == 2 and pos and pos != 'BB':
                    vp = 'BB'  # най-често BB defend-ва vs raise
                elif alive == 2 and pos == 'BB':
                    vp = 'BTN'  # default villain IP
                # ── Stack/pot derivation за SPR ──────────────────────────
                stack_bb = None
                pot_bb = None
                if w.bb_size > 0 and w.hero_stack_chips > 0:
                    stack_bb = w.hero_stack_chips / w.bb_size
                if w.bb_size > 0 and facing and w.call_amount > 0:
                    # Приблизителна оценка на pot: предполагаме villain бет ~50% пот
                    # → pot преди неговия бет ≈ 2 * call; pot след бет ≈ 3 * call (excl hero call)
                    pot_bb = (w.call_amount * 3) / w.bb_size
                elif w.bb_size > 0 and not facing:
                    # PFA unопонен: grob pot ≈ 3bb * num_callers + blinds; approximate as 6bb
                    pot_bb = 6.0
                # Multiway: alive - 1 = opponents (минус hero)
                num_opp = max(1, (len(w.occupied_seats) - len(w.folded_seats)) - 1)

                r = postflop_analyze(hole, board, facing_bet=facing, hero_pos=pos, villain_pos=vp,
                                     stack_bb=stack_bb, pot_bb=pot_bb, num_opponents=num_opp)
                street_name = w.street.upper() if w.street != 'preflop' else "FLOP"
                action_text = r['action']
                if facing:
                    action_text = f"[vs BET {call_bb:.1f}BB] {action_text}"
                self.post_action_var.set(f"[{street_name}] {action_text}")
                self.post_hand_var.set(r['hand'])
                self.post_reason_var.set(r["reason"])
                self.post_action_lbl.config(fg=r["color"])
                self.sizing_var.set(r.get("sizing", ""))
                # ── ТИ ИМАШ / ТЕ БИЕ поленце ──
                hero_label = r.get("hero_label", "")
                threats = r.get("threats", [])
                if hero_label:
                    self.threats_have_var.set(f"ТИ ИМАШ: {hero_label}")
                else:
                    self.threats_have_var.set("")
                if threats:
                    self.threats_beat_var.set("ТЕ БИЕ: " + ", ".join(threats))
                else:
                    self.threats_beat_var.set("ТЕ БИЕ: nothing на този борд")
                # Strategy log: postflop advice
                if self.strategy_logger and w.hand_id:
                    try:
                        self.strategy_logger.log_advice(
                            w.hand_id, w.street, pos, hole, board,
                            bool(facing), pot_bb, stack_bb, num_opp, r,
                        )
                    except Exception:
                        pass
            else:
                self.post_action_var.set("")
                self.post_hand_var.set("")
                self.post_reason_var.set("Card overlap!")
                self.post_action_lbl.config(fg="#ff6060")
                self.sizing_var.set("")
                self.threats_have_var.set("")
                self.threats_beat_var.set("")
        elif len(hole) == 2:
            self.post_action_var.set("Preflop")
            self.post_hand_var.set("")
            self.post_reason_var.set("Board auto-detects...")
            self.post_action_lbl.config(fg="#666")
            self.sizing_var.set("")
            self.threats_have_var.set("")
            self.threats_beat_var.set("")
        else:
            self.post_action_var.set("")
            self.post_hand_var.set("")
            self.post_reason_var.set("")
            self.post_action_lbl.config(fg="#888")
            self.sizing_var.set("")
            self.threats_have_var.set("")
            self.threats_beat_var.set("")


if __name__ == "__main__":
    app = LiveAdvisor()
    app.mainloop()
