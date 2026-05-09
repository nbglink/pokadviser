const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, LevelFormat, TabStopType, TabStopPosition,
  WidthType, ShadingType, BorderStyle, PageBreak, PageOrientation
} = require('docx');

const ARIAL = "Arial";
const SIZE_BODY = 22;   // 11pt
const SIZE_SMALL = 20;  // 10pt
const SIZE_CODE = 20;
const CONSOLAS = "Consolas";

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120, before: opts.before ?? 0 },
    alignment: opts.align ?? AlignmentType.LEFT,
    children: [new TextRun({ text, font: opts.font ?? ARIAL, size: opts.size ?? SIZE_BODY,
                              bold: opts.bold, italics: opts.italics, color: opts.color })],
    ...(opts.heading ? { heading: opts.heading } : {}),
  });
}

function pRuns(runs, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120 },
    alignment: opts.align ?? AlignmentType.LEFT,
    children: runs.map(r => new TextRun({
      font: r.font ?? ARIAL, size: r.size ?? SIZE_BODY,
      text: r.text, bold: r.bold, italics: r.italics, color: r.color,
    })),
  });
}

function bullet(text, level = 0, opts = {}) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { after: 80 },
    children: [new TextRun({ text, font: ARIAL, size: SIZE_BODY, bold: opts.bold })],
  });
}

function bulletRuns(runs, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { after: 80 },
    children: runs.map(r => new TextRun({
      text: r.text, font: r.font ?? ARIAL, size: r.size ?? SIZE_BODY,
      bold: r.bold, italics: r.italics, color: r.color,
    })),
  });
}

function code(text) {
  return new Paragraph({
    spacing: { before: 80, after: 80 },
    shading: { fill: "F2F2F2", type: ShadingType.CLEAR },
    children: [new TextRun({ text, font: CONSOLAS, size: SIZE_CODE })],
  });
}

const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: border, bottom: border, left: border, right: border };

function cell(text, opts = {}) {
  return new TableCell({
    borders,
    width: { size: opts.width, type: WidthType.DXA },
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      children: [new TextRun({
        text, font: opts.font ?? ARIAL, size: opts.size ?? SIZE_SMALL,
        bold: opts.bold, color: opts.color,
      })],
    })],
  });
}

const doc = new Document({
  creator: "Claude",
  title: "Poker Advisor — Ръководство за потребителя",
  styles: {
    default: { document: { run: { font: ARIAL, size: SIZE_BODY } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: ARIAL },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: ARIAL, color: "2E5C8A" },
        paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: ARIAL },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "○", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
        ] },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children: [
      // ── ТИТУЛНА СТРАНИЦА ──
      p("Poker Advisor", { heading: HeadingLevel.HEADING_1, align: AlignmentType.CENTER, after: 200 }),
      p("Ръководство за потребителя", {
        size: 28, italics: true, align: AlignmentType.CENTER, after: 600, color: "555555",
      }),
      p("Real-time GTO advisor за PokerStars.BG (No-Limit Hold'em)", {
        size: 22, align: AlignmentType.CENTER, after: 100, color: "777777",
      }),
      p("Версия от 9 май 2026", {
        size: 20, align: AlignmentType.CENTER, italics: true, after: 800, color: "999999",
      }),

      // ── 1. КАКВО Е ТОВА ──
      p("1. Какво е това", { heading: HeadingLevel.HEADING_1 }),
      p("Poker Advisor е Python програмка с графичен интерфейс, която чете лога на PokerStars.BG в реално време и ти препоръчва как да играеш всяка ръка. Използва GTO-aligned стратегия (Upswing Poker doctrine — 8 bet sizing rules, SPR buckets, range theory)."),
      p("Какво прави:", { bold: true, after: 80 }),
      bullet("Авто-чете board, позиция, улица, pot, stack от лога"),
      bullet("Сканира 2-те ти ръчни карти от screenshot (OCR)"),
      bullet("Изчислява препоръчано действие (FOLD / CHECK / CALL / BET / RAISE)"),
      bullet("Показва процент срещу villain range, decision strip с ключовите числа"),
      bullet("Адаптира се за multiway, SPR commit zones, flush threats"),
      p("Какво НЕ прави:", { bold: true, after: 80 }),
      bullet("Не играе вместо теб (само съветва — ти кликаш бутоните)"),
      bullet("Не следи multi-tabling (само една маса)"),
      bullet("Не модели villain range street-by-street (взима opening range на тяхната позиция)"),

      // ── 2. ИНСТАЛАЦИЯ И СТАРТИРАНЕ ──
      p("2. Стартиране", { heading: HeadingLevel.HEADING_1 }),
      p("Препоръка: PokerStars.BG да е отворен и активен на първоначалната позиция."),
      p("Стъпки:", { bold: true, after: 80 }),
      bullet("Отвори PowerShell"),
      bullet("Навигирай до директорията:"),
      code("cd C:\\Users\\Admin\\claude"),
      bullet("Стартирай advisor-а:"),
      code("python poker_live.py"),
      bullet("Прозорецът се отваря — започни ръка в PokerStars и наблюдавай как полетата се пълнят автоматично"),
      p("Зависимости:", { bold: true, after: 80 }),
      bullet("Python 3.10+"),
      bullet("EasyOCR + Tesseract (за scanner-а)"),
      bullet("tkinter (built-in в Python)"),
      bullet("mss + pillow (за screenshot capture)"),
      p("Ако scanner-ът не работи — програмата пак тръгва, но ще трябва да въвеждаш hole картите ръчно с бутоните."),

      // ── 3. КАКВО ВИЖДАШ НА ЕКРАНА ──
      p("3. Какво виждаш на екрана", { heading: HeadingLevel.HEADING_1 }),
      p("Прозорецът е разделен на секции отгоре надолу:"),

      p("3.1 Top bar — статус", { heading: HeadingLevel.HEADING_2 }),
      p("Показва дали логът е намерен, дали има активна ръка, hand_id, твоята позиция (UTG/MP/CO/BTN/SB/BB) с цветен badge."),

      p("3.2 Cards", { heading: HeadingLevel.HEADING_2 }),
      p("Две hole карти отляво (твоите) + до 5 board карти отдясно. Hole картите са със светъл фон, board — сини. Празни слота са сиви."),

      p("3.3 Texture", { heading: HeadingLevel.HEADING_2 }),
      p("Описание на текстурата на board: DRY / WET / MONO! / PAIRED / CONNECTED. Малък зелен текст, не изисква действие — просто индикатор."),

      p("3.4 PREFLOP секция", { heading: HeadingLevel.HEADING_2 }),
      p("Голям action banner: RAISE / CALL / FOLD + кратка причина."),
      pRuns([
        { text: "Важно: ", bold: true },
        { text: "когато board има 3+ карти (играем postflop), preflop секцията автоматично се " },
        { text: "dim-ва (сив малък текст)", italics: true },
        { text: " — фокусът се прехвърля на постфлоп. Това предотвратява visual confusion от два едновременни colored verdicta." },
      ]),

      p("3.5 POSTFLOP секция — основната", { heading: HeadingLevel.HEADING_2 }),
      p("Тук е основният съвет. Подсекции отгоре надолу:"),

      p("Action banner", { heading: HeadingLevel.HEADING_3 }),
      p("Голям златен/червен/зелен текст: BET 50% / CHECK / CALL / FOLD / RAISE (commit). Това е препоръчаното действие. Цветът е семантика:"),
      bulletRuns([
        { text: "Зелено", color: "60ff60", bold: true },
        { text: " — value bet / агресивен ход" },
      ]),
      bulletRuns([
        { text: "Златно/жълто", color: "f0d060", bold: true },
        { text: " — стандартен play, mix, неутрално" },
      ]),
      bulletRuns([
        { text: "Амбър/оранж", color: "ffb040", bold: true },
        { text: " — каутион, conditional (call малък / fold голям)" },
      ]),
      bulletRuns([
        { text: "Червено", color: "ff6060", bold: true },
        { text: " — fold / give up" },
      ]),

      p("Hand label", { heading: HeadingLevel.HEADING_3 }),
      p("Описва текущата ти ръка в текст: \"TP A +K kicker + NFD\", \"Mid pair (8) + GS\", \"FLUSH\", \"Сет 777\"."),
      p("Включва made hand + draw (ако има): NFD = nut flush draw, FD = flush draw, BFD = backdoor flush draw, OESD = open-ended straight draw, GS = gutshot."),

      p("Decision strip", { heading: HeadingLevel.HEADING_3 }),
      p("Компактен ред с ключовите числа за бързо четене:"),
      code("Pot 14.2BB · Stack 80BB · SPR 5.6 · need 25% eq · ТИ ~58%"),
      bullet("Pot: текущ пот в Big Blinds"),
      bullet("Stack: твоят ефективен стак в BB"),
      bullet("SPR: stack-to-pot ratio (важно за commit decisions)"),
      bullet("need X% eq: ако сме facing bet, каква equity ти трябва за +EV call (pot odds)"),
      bullet("ТИ ~N%: % от opening range на villain който ти биеш в момента (приблизителен)"),

      p("ТИ ИМАШ / ТЕ БИЕ поленце", { heading: HeadingLevel.HEADING_3 }),
      p("Цветно поленце с две реда:"),
      bulletRuns([
        { text: "ТИ ИМАШ: ", bold: true },
        { text: "име на ръката + (% от range) — какво държиш и какъв % от range-а биеш" },
      ]),
      bulletRuns([
        { text: "ТЕ БИЕ: ", bold: true },
        { text: "категории които те бият (flush, straight, set...) + (% от range) — какъв % те бие" },
      ]),
      p("Цветът на цялото поленце е твоят бърз semantic сигнал:", { bold: true, after: 80 }),

      // Color band table
      new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [1800, 1800, 5760],
        rows: [
          new TableRow({ children: [
            cell("Beat %", { width: 1800, fill: "404040", color: "FFFFFF", bold: true }),
            cell("Цвят", { width: 1800, fill: "404040", color: "FFFFFF", bold: true }),
            cell("Значение", { width: 5760, fill: "404040", color: "FFFFFF", bold: true }),
          ]}),
          new TableRow({ children: [
            cell("≥ 65%", { width: 1800 }),
            cell("Зелено", { width: 1800, fill: "1A2A1A", color: "88FF88", bold: true }),
            cell("OK to bet за value — ти доминираш range-а", { width: 5760 }),
          ]}),
          new TableRow({ children: [
            cell("35–64%", { width: 1800 }),
            cell("Амбър", { width: 1800, fill: "2A261A", color: "FFD866", bold: true }),
            cell("Каутион — coin-flip-ish, mix играч / pot control", { width: 5760 }),
          ]}),
          new TableRow({ children: [
            cell("< 35%", { width: 1800 }),
            cell("Червено", { width: 1800, fill: "2A1A1A", color: "FFAAAA", bold: true }),
            cell("Give up / call only — много от range-а те бие", { width: 5760 }),
          ]}),
        ],
      }),
      p("", { after: 100 }),
      p("С hysteresis: бандът не премигва когато процентът hover-ва около праг (60/68 за зелено, 30/38 за червено)."),

      p("Reason", { heading: HeadingLevel.HEADING_3 }),
      p("Под decision strip-а — пълно текстово обяснение защо този съвет, plus annotation в скоби: [IP/OOP], [SPR commit zone], [Multiway X опонента], [Flush заплаха]."),

      p("Sizing", { heading: HeadingLevel.HEADING_3 }),
      p("Препоръчан bet size като % от pot — \"Sizing: 33% пот (dry: малко но често)\"."),

      // ── 4. КАК ДА ЧЕТЕШ СЪВЕТА ──
      p("4. Как да четеш съвета", { heading: HeadingLevel.HEADING_1 }),
      p("Когато имаш 3 секунди (преди да кликнеш бутона):", { bold: true }),
      bullet("Action banner — какво (RAISE/CALL/CHECK/FOLD)"),
      bullet("Decision strip — at-a-glance числа (особено need X% eq vs ТИ ~N%)"),
      bullet("Цветът на ТИ ИМАШ frame — зелено=агресия OK, червено=каутион"),
      p("Когато имаш 10 секунди:", { bold: true, before: 100 }),
      bullet("Прочети Hand label — точно какво държиш + какви draws"),
      bullet("Прочети ТЕ БИЕ — какво да очакваш от villain"),
      bullet("Reason text — защо engine-ът съветва това (особено [annotations])"),

      p("5. Сигнали за внимание", { heading: HeadingLevel.HEADING_1 }),
      p("Engine-ът автоматично downgrade-ва агресията в специфични ситуации. Виж тези markers в reason-а:"),

      p("[Multiway X опонента]", { heading: HeadingLevel.HEADING_2 }),
      p("Когато си в pot с 2+ opponents, equity-то ти пада. Engine-ът сваля RAISE→CALL и BET→CHECK за всичко освен monster ръце (FLUSH, STRAIGHT, Сет, 2 pair). Не bluff-вай в multiway."),

      p("[SPR=X commit zone]", { heading: HeadingLevel.HEADING_2 }),
      p("SPR < 3 значи че stack-а ти е малък спрямо пота — TP+ обикновено стига за all-in. Engine-ът пуска по-агресивни stack-off препоръки."),

      p("[Flush заплаха: 3♥ на борда, ти имаш 0]", { heading: HeadingLevel.HEADING_2 }),
      p("Когато board има 3+ от една боя и ти нямаш карта от тая боя, engine-ът:"),
      bullet("Downgrade-ва RAISE (commit) → CALL малък / FOLD голям"),
      bullet("Downgrade-ва BET → CHECK"),
      p("Изключение: ако имаш FLUSH/STRAIGHT/Set/2pair+ — запазва агресията (бияш villain flush-овете)."),

      // PAGE BREAK
      new Paragraph({ children: [new PageBreak()] }),

      // ── 6. ОГРАНИЧЕНИЯ ──
      p("6. Ограничения", { heading: HeadingLevel.HEADING_1 }),
      p("Какво engine-ът не моделира идеално:"),
      bullet("Villain range е opening range на тяхната позиция, не street-narrowed (когато villain bet-ва на river, реалният му range е по-тесен от opening)"),
      bullet("Beat % е приблизителен — не отчита draw-equity, не прави точен 5-card eval за flush kickers / straight high cards"),
      bullet("Pot tracking under-counts villain calls в multiway (виждаме hero actions + first villain bet, не и multiple callers)"),
      bullet("Само 1 маса (single-tabling)"),
      bullet("Само cash + tournament holdem; не Zoom-specific adjustments"),

      // ── 7. DEBUG ──
      p("7. Debug при проблеми", { heading: HeadingLevel.HEADING_1 }),

      p("Scanner не познава картите", { heading: HeadingLevel.HEADING_2 }),
      bullet("Натисни \"Debug scan\" бутона"),
      bullet("Отваря се папка %TEMP%\\poker_scan_debug_<timestamp>\\ с screenshots + diagnostics"),
      bullet("Алтернатива: въведи hole картите ръчно с бутоните (rank + suit)"),

      p("Грешна позиция", { heading: HeadingLevel.HEADING_2 }),
      bullet("Engine-ът показва грешна (UTG/CO/BTN…)"),
      bullet("Често Zoom \"скрива\" pre-actions; на 9-max понякога heuristic-ът греши"),
      bullet("Workaround: рестартирай ръката или поправи мисленно (приоритизирай твоята интуиция)"),

      p("Pot/SPR изглежда грешно", { heading: HeadingLevel.HEADING_2 }),
      bullet("Pot accumulator зависи от parsed actions; ако сте midhand при стартиране на advisor-а, pot ще е under-counted"),
      bullet("Стартирай advisor-а ПРЕДИ или ПО ВРЕМЕ на нова ръка за точно tracking"),

      p("Логът не се чете", { heading: HeadingLevel.HEADING_2 }),
      bullet("Default път: C:\\Users\\Admin\\AppData\\Local\\PokerStars.BG\\PokerStars.log.0"),
      bullet("Ако PS е инсталиран другаде — редактирай LOG_DIR в poker_live.py"),

      // ── 8. БЪРЗ REFERENCE ──
      p("8. Бърз reference на термините", { heading: HeadingLevel.HEADING_1 }),
      new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [2000, 7360],
        rows: [
          new TableRow({ children: [
            cell("Термин", { width: 2000, fill: "404040", color: "FFFFFF", bold: true }),
            cell("Значение", { width: 7360, fill: "404040", color: "FFFFFF", bold: true }),
          ]}),
          new TableRow({ children: [
            cell("TP / TPTK", { width: 2000, bold: true }),
            cell("Top Pair / Top Pair Top Kicker — двойка с най-високата board карта", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("FD / NFD", { width: 2000, bold: true }),
            cell("Flush Draw / Nut Flush Draw — 4 карти от една боя; nut = с асо за топ flush", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("BFD", { width: 2000, bold: true }),
            cell("Backdoor Flush Draw — 3 карти от една боя (нужни 2 ривъра)", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("OESD", { width: 2000, bold: true }),
            cell("Open-Ended Straight Draw — 4 последователни (8 outs към straight)", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("GS", { width: 2000, bold: true }),
            cell("Gutshot — straight draw с 4 outs (един gap по средата)", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("SPR", { width: 2000, bold: true }),
            cell("Stack-to-Pot Ratio. <3=commit, 3-6=standard, 6-12=cautious, >12=deep", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("MDF", { width: 2000, bold: true }),
            cell("Minimum Defense Frequency — % range което трябва да защитиш срещу bet", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("BB / BBs", { width: 2000, bold: true }),
            cell("Big Blind units. Stack/pot винаги се мерят в BB", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("IP / OOP", { width: 2000, bold: true }),
            cell("In Position / Out Of Position — играеш ли последен на улицата", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("Range %", { width: 2000, bold: true }),
            cell("% от combos в opening range-а на villain", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("Equity", { width: 2000, bold: true }),
            cell("Шанс да спечелиш showdown (или да подобриш до winning hand)", { width: 7360 }),
          ]}),
          new TableRow({ children: [
            cell("Pot odds", { width: 2000, bold: true }),
            cell("call / (pot + call) — каква equity ти трябва за +EV call", { width: 7360 }),
          ]}),
        ],
      }),

      p("", { after: 200 }),
      // Footer
      p("— край на ръководството —", {
        align: AlignmentType.CENTER, italics: true, color: "999999", size: 20, before: 400,
      }),
    ],
  }],
});

Packer.toBuffer(doc).then(buf => {
  const out = "C:\\Users\\Admin\\claude\\docs\\Poker_Advisor_Guide_BG.docx";
  fs.writeFileSync(out, buf);
  console.log("Wrote", out, "size:", buf.length, "bytes");
});
