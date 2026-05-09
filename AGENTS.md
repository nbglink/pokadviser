# Poker Advisor — проектна памет

## Какво е това

Real-time No-Limit Hold'em advisor за PokerStars.BG (Bella/Mercury IX клиент).
Чете PS лог файла за board/position/street, скенира hole картите с OCR, и дава
GTO-aligned съвети на всяка улица.

Референтна доктрина: **Upswing Poker** (https://upswingpoker.com/) — 8 bet sizing
rules, 3 concepts (Positional/Range/Nut advantage), SPR buckets, float theory.

## Файлове

| Файл | Роля |
|---|---|
| `poker_oop_tool.py` | Strategy engine (preflop + postflop, pure logic, без UI) |
| `poker_live.py` | tkinter GUI + LogWatcher (parse PS log) + scanner wiring |
| `poker_scanner.py` | OCR скенер (EasyOCR + Tesseract) + button detector |
| `poker_logger.py` | Наблюдател за PS лога (standalone debug tool) |
| `scanner_config.json` | Калибрация + thresholds (auto-generated) |
| `scanner_templates/` | OCR templates (auto-populated от training mode) |

## Архитектурни принципи

1. **Разделение**: `poker_oop_tool.py` е pure strategy (no UI, no I/O). `poker_live.py` е само UI + wiring. `poker_scanner.py` е I/O + CV.
2. **Лог → авто**: board, position, street, facing_bet, call_amount, bb_size, pot, stack → всички се извличат от MSG_0007/MSG_0020/Board/Players redactions в PS лога.
3. **Scanner → hole cards only**: само 2-те ръчни карти идват от screenshot, всичко друго е log-based.
4. **Ratios, не пиксели**: scanner калибрацията е resolution-independent (работи на 1920×1080 и 5120×1440).
5. **Graceful degradation**: ако EasyOCR/cv2/mss липсват, scanner е disabled но advisor работи в manual mode.

## Strategy engine (`poker_oop_tool.py`)

### Константи най-отгоре
- Outs: `OUTS_FD=9, OUTS_OESD=8, OUTS_GUTSHOT=4, OUTS_BFD=1`
- SPR buckets: `SPR_COMMIT=3.0, SPR_STANDARD_MAX=6.0, SPR_CAUTIOUS_MAX=12.0`
- Bet sizings: `BET_SMALL=0.33, BET_MED=0.50, BET_LARGE=0.66, BET_POT=1.00`
- Board-specific cbet sizings: `FLOP_DRY_PCT`, `FLOP_WET_PCT`, `FLOP_PAIRED_PCT`, etc.

### Preflop (`preflop_analyze`)
- `OPEN_RANGES`: GTO-aligned 6-max (UTG ~15%, MP ~19%, CO ~27%, BTN ~45%, SB ~35%)
- `THREEBET_ALWAYS/VALUE/BLUFF`: solver-aligned 3-bet ranges
- `FOURBET_VALUE = {AA, KK, AKs}`, `FOURBET_BLUFF = {A5s-A2s}` (Ace blockers), `FOURBET_MIXED`
- `CALL_VS_3BET_IP/OOP`: различни ranges (OOP много по-тесен)
- Route: `facing_3bet` → `_vs_3bet`, `facing_raise` → `_vs_raise`, else → `_rfi`

### Postflop (`postflop_analyze`)
Signature: `(hole, board, facing_bet, hero_pos, villain_pos, stack_bb, pot_bb, num_opponents)`

Логика:
- SPR bucket → `commit/standard/cautious/deep` (влияе на TP/overpair stack-off behavior)
- Multiway (num_opponents ≥ 2) → `_mw_adjust` demotes RAISE→CALL, BET→CHECK за не-монстри
- Board texture → sizing (Upswing Rules 3-8)

### Utility functions
- `equity_from_outs(outs, streets_left)` — Rule of 2 & 4
- `pot_odds_needed(bet_pct)` — `bet_pct / (1 + 2*bet_pct)`
- `implied_odds(outs, pot, bet, stack, ...)` — verdict + required_future BB
- `rio_penalty(draw_type, nut_draw, spr_name, ip)` — equity multiplier 0.65-1.0
- `check_raise_frequency(bi, hand_strength, ip, spr_name)` — честота 0-1 по текстура
- `board_info(board)` — текстурен анализ (dry/wet/paired/connected)
- `spr_bucket(spr)` — bucket name + note

## Scanner (`poker_scanner.py`)

### OCR pipeline
1. **EasyOCR primary** — multi-scale (6×, 4×, 8×), early-exit at conf ≥ 0.90, sharpen+contrast enhancement
2. **Tesseract fallback** — когато EasyOCR fail-не или conf < 0.30
3. **Tiebreakers**:
   - **T↔4**: когато EasyOCR каже T → cross-check с Tesseract (винаги), "4" override при conf ≥ 0.6
   - **6↔7**: Tesseract cross-check + shape-based detector (flood-fill за loop detection)

### Suit detection (HSV)
- **Exclude**: white (s<25, v>200), green_felt (h∈[35,85], s∈[15,70), v<100), gray_felt (s<30, v∈[45,170]), purple_felt (h∈[130,170], s∈[20,150))
- **Red ♥**: h≤12 or h≥168, s>50, v>80
- **Blue ♦**: h∈[95,135], **s>120**, v>60 — висока saturation за да не бъркаме с лилав филц
- **Green ♣**: h∈[35,90], s≥60, v>50
- **Black ♠**: v<45, s<40
- Threshold: total ≥ 3 pixels

**Ключово**: blue ink е много по-saturated (s>120) от лилавия филц (s<150). Green felt иска s≥15 за да НЕ погълне truly black ink (s≈0, случайна hue).

### Dealer button detection
- HoughCircles + **red center check** (≥5% red pixels в центъра) за да избегнем false positives от "77" overlay
- Scoring: `0.4 * brightness_norm + 0.6 * red_ratio_norm`

### Confidence thresholds (scanner_config.json)
- `auto_confirm_threshold: 0.30` — auto-accept под тази граница (почти всички scans)
- `confirm_threshold: 0.15` — под тази — show confirm UI

## Log parsing (`poker_live.py::LogWatcher`)

Лог файл: `C:\Users\Admin\AppData\Local\PokerStars.BG\PokerStars.log.0`

### Ключови PS лог сигнали
- `MSG_0080` → нова ръка (trigger за scan)
- `MSG_0007` → hero action options (parse vMn/vMx/a= за call/check/bet/raise)
- `MSG_0020` → друг играч действа (count за позиция fallback)
- `Board { Before/After { X,Y,Z } }` → flop/turn/river
- `Player { seat } Cards { 2 }` → occupied seats
- `Player { seat } Cards {}` → fold detection
- `Players { {c0,c1}, -, {--,--}, ... }` → accurate player count (Zoom-compatible)

### Derived state
- `hero_position`: от blind option signals (P/p) + counting fallback
- `bb_size`: от vMin на E (preflop min-raise=2×BB), или B (postflop min-bet=BB), или call_amount
- `hero_stack_chips`: от vMx на E/B (max raise/bet = оставащ стак)
- `pot_chips`: approximated (3× call_amount когато facing_bet)

### Позиция — Zoom vs cash
Zoom "скрива" pre-actions (instant calls/folds преди View), така че MSG_0020 count е
ненадежден. Primary signals: `a=P` (BB post), `a=p` (SB post), `can_check` preflop →
BB, `call_amount == bb_size // 2` → SB. Counting fallback само когато нищо друго.

## UI (`LiveAdvisor` в poker_live.py)

- Hole cards: manual pick (rank + suit бутони) ИЛИ auto-scan (когато checkbox е ON)
- Board: auto от лог
- Auto-scan flow: MSG_0080 → delay (500ms) → scanner.scan() → ако conf ≥ auto_confirm → apply; иначе confirm UI
- Training mode: всяко ръчно въвеждане записва templates (disabled в production)
- Debug scan бутон (при manual click на "Debug scan"): пише `debug.txt` + card1/2.png + window.png в `%TEMP%\poker_scan_debug_<timestamp>\`

## Known themes + calibration gotchas

- **Green felt** (default): s<70, v<100 exclusion OK
- **Gray felt** (theme update): s<30, v∈[45,170]
- **Purple/Lavender felt**: h∈[138,165] — **стеснено от 130 за да не ядем синия ♦**
- **Red PS logo на dealer button**: изисква red-center check за да не object detect "77" overlay-а на играч

## Ограничения / out of scope

- Без сканиране на board карти (те идват от лога)
- Без detection на действия/стакове от screenshots (идват от лога)
- Само single-table
- Без мобилна версия
- Templates не се комитват в git (user-specific)

## Обичайни промени

- **Добавяне на нова позиция/range**: редактирай `_build_open_ranges()` в poker_oop_tool.py
- **Нов OCR tiebreaker**: добави в `detect_rank()` pattern като T/4 или 6/7
- **Нова felt тема**: добави exclusion mask в `detect_suit()`
- **Нов лог сигнал**: разшири `_parse` в `LogWatcher`

## Тестване

```python
# Sanity check на imports
python -c "from poker_oop_tool import preflop_analyze, postflop_analyze; print('ok')"

# Regression tests (ръчно)
python -c "
from poker_oop_tool import *
r = preflop_analyze((('A','h'),('A','s')), hero_pos='CO', facing_3bet=True, three_bettor_pos='BTN')
assert '4-BET' in r['action']
r = postflop_analyze([('A','h'),('K','s')], [('A','d'),('7','c'),('2','h')],
                    facing_bet=True, hero_pos='CO', num_opponents=3)
assert 'RAISE' not in r['action']  # multiway downgrade
print('regression OK')
"
```

## Debug tips

- Scanner не познава? → натисни "Debug scan" → отваря `%TEMP%\poker_scan_debug_<ts>\` с screenshots + per-card rank/suit diagnostics
- Button не се детектира? → натисни "Debug btn" → `%TEMP%\poker_btn_<ts>\btn.txt`
- Лог не се чете? → провери `LOG_DIR` в poker_live.py (сега `C:\Users\Admin\AppData\Local\PokerStars.BG`)
- Wrong position? → `_position_locked` може да не е тригернат; виж `_parse_actions` за P/p/can_check signals
