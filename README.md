# Pokadviser

Real-time No-Limit Hold'em advisor за PokerStars.BG (Bella/Mercury IX клиент).

Чете PokerStars лог файла за board / position / street, скенира hole картите с OCR,
и дава GTO-aligned съвети на всяка улица.

## Какво прави

- **Auto board / position / street detection** от PS лога (MSG_0080, MSG_0007, etc.)
- **OCR скенер** за 2-те ръчни карти (EasyOCR + Tesseract fallback)
- **Dealer button detection** чрез HoughCircles + red-center signature
- **GTO-aligned strategy engine** базиран на Upswing Poker доктрина
- **"ТИ ИМАШ / ТЕ БИЕ"** поленце с класификация на ръката + threats
- **Multiway adjustment**, SPR buckets, board texture analysis
- Поддръжка за 6-max cash и Zoom

## Файлове

| Файл | Роля |
|---|---|
| `poker_oop_tool.py` | Strategy engine (preflop + postflop, pure logic) |
| `poker_live.py` | tkinter GUI + LogWatcher + scanner wiring |
| `poker_scanner.py` | OCR скенер (EasyOCR + Tesseract) + button detector |
| `poker_logger.py` | Standalone лог наблюдател (debug) |
| `poker_strategy_log.py` | JSONL логер на advice + actions |
| `scanner_config.json` | Калибрация + thresholds (auto-generated) |

## Инсталация

```bash
pip install -r requirements.txt
```

Optional за по-добро OCR:
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (Windows installer)

## Стартиране

```bash
python poker_live.py
```

GUI ще се отвори. Първо натисни **"Калибрирай"** за да маркираш hole card region
(2 клика върху прозореца на PokerStars). После може да включиш auto-scan.

## Архитектурни принципи

1. **Разделение**: `poker_oop_tool.py` е pure strategy (no UI, no I/O).
   `poker_live.py` е само UI + wiring. `poker_scanner.py` е I/O + CV.
2. **Лог → авто**: board, position, street, facing_bet, call_amount, bb_size,
   pot, stack — всички се извличат от PokerStars лога.
3. **Scanner → hole cards only**: само 2-те ръчни карти идват от screenshot.
4. **Ratios, не пиксели**: scanner калибрацията е resolution-independent.
5. **Graceful degradation**: ако EasyOCR/cv2/mss липсват, scanner е disabled
   но advisor работи в manual mode.

## Strategy engine highlights

- **8 Upswing bet sizing rules** (dry/wet/paired/connected board adjustments)
- **3 Concepts**: Positional, Range, Nut advantage
- **SPR buckets**: commit / standard / cautious / deep
- **Made hand priority**: Quads > Full House > Flush > Straight > Set > Trips > 2pair > Pair
- **Multiway downgrade**: TP = 1 улица, draws lose value, no bluff c-bets

## Лимитации (out of scope)

- Без четене на board от screenshots (идва от лог)
- Без detection на действия/стакове от screenshots (от лог)
- Single-table only
- Без мобилна версия

## Документация

- `CLAUDE.md` — проектна памет (архитектура, conventions, debug tips)
- `POKER_LEGENDA.txt` — стратегическа справка (Upswing Poker)

## License

Personal use. Reference doctrine: [Upswing Poker](https://upswingpoker.com/).
