# Pokadviser

Real-time No-Limit Hold'em advisor for PokerStars.BG (Bella/Mercury IX client).

Reads the PokerStars log file for board / position / street, scans hole cards
with OCR, and provides GTO-aligned advice on every street.

## Features

- **Auto board / position / street detection** from the PS log (MSG_0080,
  MSG_0007, etc.)
- **OCR scanner** for the 2 hole cards (EasyOCR primary + Tesseract fallback)
- **Dealer button detection** via HoughCircles + red-center signature
- **GTO-aligned strategy engine** based on Upswing Poker doctrine
- **"YOU HAVE / YOU LOSE TO" panel** with hand classification + threats
- **Multiway adjustment**, SPR buckets, board texture analysis
- Supports 6-max cash and Zoom

## Files

| File | Role |
|---|---|
| `poker_oop_tool.py` | Strategy engine (preflop + postflop, pure logic) |
| `poker_live.py` | tkinter GUI + LogWatcher + scanner wiring |
| `poker_scanner.py` | OCR scanner (EasyOCR + Tesseract) + button detector |
| `poker_logger.py` | Standalone log watcher (debug) |
| `poker_strategy_log.py` | JSONL logger for advice + actions |
| `scanner_config.json` | Calibration + thresholds (auto-generated) |

## Installation

```bash
pip install -r requirements.txt
```

Optional for better OCR accuracy:
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (Windows installer)

## Running

```bash
python poker_live.py
```

The GUI will open. First press **"Calibrate"** to mark the hole card region
(2 clicks on the PokerStars window). Then you can enable auto-scan.

## Architectural principles

1. **Separation of concerns**: `poker_oop_tool.py` is pure strategy (no UI,
   no I/O). `poker_live.py` is just UI + wiring. `poker_scanner.py` is I/O + CV.
2. **Log → auto**: board, position, street, facing_bet, call_amount, bb_size,
   pot, stack — all extracted from the PokerStars log.
3. **Scanner → hole cards only**: only the 2 hole cards come from a screenshot.
4. **Ratios, not pixels**: scanner calibration is resolution-independent.
5. **Graceful degradation**: if EasyOCR / cv2 / mss are missing, the scanner
   is disabled but the advisor still works in manual mode.

## Strategy engine highlights

- **8 Upswing bet sizing rules** (dry/wet/paired/connected board adjustments)
- **3 Concepts**: Positional, Range, Nut advantage
- **SPR buckets**: commit / standard / cautious / deep
- **Made hand priority**: Quads > Full House > Flush > Straight > Set > Trips > 2pair > Pair
- **Multiway downgrade**: TP = 1 street, draws lose value, no bluff c-bets

## Out of scope

- No board reading from screenshots (sourced from log)
- No action / stack detection from screenshots (sourced from log)
- Single-table only
- No mobile version

## Documentation

- `CLAUDE.md` — project memory (architecture, conventions, debug tips)
- `POKER_LEGENDA.txt` — strategy reference (Upswing Poker)

## License

Personal use. Reference doctrine: [Upswing Poker](https://upswingpoker.com/).
