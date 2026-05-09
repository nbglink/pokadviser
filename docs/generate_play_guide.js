const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, LevelFormat, WidthType, ShadingType,
  BorderStyle, PageBreak, PageOrientation
} = require('docx');

const ARIAL = "Arial";
const SIZE_BODY = 22;
const SIZE_SMALL = 20;
const CONSOLAS = "Consolas";

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120, before: opts.before ?? 0 },
    alignment: opts.align ?? AlignmentType.LEFT,
    children: [new TextRun({
      text, font: opts.font ?? ARIAL, size: opts.size ?? SIZE_BODY,
      bold: opts.bold, italics: opts.italics, color: opts.color
    })],
    ...(opts.heading ? { heading: opts.heading } : {}),
  });
}

function pRuns(runs, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120 },
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
    children: [new TextRun({ text, font: CONSOLAS, size: 20 })],
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

// Helper for example boxes — heading + scenario fields + advice + interpretation
function example(title, scenario, advice, interpret) {
  return [
    p(title, { heading: HeadingLevel.HEADING_3 }),
    pRuns([{ text: "Сценарий: ", bold: true }, { text: scenario }]),
    pRuns([
      { text: "Engine препоръчва: ", bold: true },
      { text: advice, font: CONSOLAS, color: "2E5C8A" },
    ]),
    pRuns([{ text: "Какво правиш: ", bold: true }, { text: interpret }]),
    p("", { after: 60 }),
  ];
}

const doc = new Document({
  creator: "Claude",
  title: "Poker Advisor — Как да играя съветите",
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
        run: { size: 24, bold: true, font: ARIAL, color: "555555" },
        paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [{
      reference: "bullets",
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "○", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
      ],
    }],
  },
  sections: [{
    properties: {
      page: { size: { width: 12240, height: 15840 },
              margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
    },
    children: [
      // ── ТИТУЛ ──
      p("Poker Advisor", { heading: HeadingLevel.HEADING_1, align: AlignmentType.CENTER, after: 100 }),
      p("Как да играя съветите", { size: 32, bold: true, align: AlignmentType.CENTER, after: 200, color: "2E5C8A" }),
      p("Практическо ръководство с примери", {
        size: 22, italics: true, align: AlignmentType.CENTER, color: "666666", after: 600,
      }),
      p("Това ръководство допълва основното (Poker_Advisor_Guide_BG.docx) и фокусира върху ПРИЛОЖЕНИЕТО — как чуваш-преглеждаш съвета и решаваш да го изпълниш или не.", {
        size: 22, align: AlignmentType.CENTER, color: "555555", after: 600,
      }),

      // ── 1. БЪРЗ FLOW ──
      p("1. 3-секундният flow", { heading: HeadingLevel.HEADING_1 }),
      p("При всяко решение, от UI-а гледаш ОТГОРЕ НАДОЛУ:"),
      bulletRuns([
        { text: "1. ACTION BANNER ", bold: true },
        { text: "(най-голям, цветен) — какво да направиш" },
      ]),
      bulletRuns([
        { text: "2. HAND LABEL ", bold: true },
        { text: "под него — какво държиш (с draw-овете включени)" },
      ]),
      bulletRuns([
        { text: "3. DECISION STRIP ", bold: true },
        { text: "— ключови числа: Pot, Stack, SPR, need eq, ТИ %" },
      ]),
      bulletRuns([
        { text: "4. ТИ ИМАШ / ТЕ БИЕ ", bold: true },
        { text: "(тънка цветна ивица отляво) — % срещу range" },
      ]),
      bulletRuns([
        { text: "5. REASON ", bold: true },
        { text: "(само ако имаш повече време) — обяснение на съвета" },
      ]),
      p("Action banner-а е твоят най-важен сигнал. Ако нямаш време за нищо друго — направи каквото казва."),

      // ── 2. ЦВЕТОВИ КОДОВЕ ──
      p("2. Цветовете на Action banner-а", { heading: HeadingLevel.HEADING_1 }),
      p("Цветът на големия action текст ти казва доколко уверена е препоръката:"),
      new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [1800, 7560],
        rows: [
          new TableRow({ children: [
            cell("Цвят", { width: 1800, fill: "404040", color: "FFFFFF", bold: true }),
            cell("Значение", { width: 7560, fill: "404040", color: "FFFFFF", bold: true }),
          ]}),
          new TableRow({ children: [
            cell("Зелено #60ff60", { width: 1800, color: "60ff60", bold: true }),
            cell("Силен value bet / агресивен ход. Изпълни без колебание.", { width: 7560 }),
          ]}),
          new TableRow({ children: [
            cell("Тъмно зелено #00e676", { width: 1800, color: "00e676", bold: true }),
            cell("Монстър ръка. Bet/raise за value, но в commit zone — готов за all-in.", { width: 7560 }),
          ]}),
          new TableRow({ children: [
            cell("Светло зелено #a0e060", { width: 1800, color: "a0e060", bold: true }),
            cell("Тънък value bet. Малко sizing, защото по-голямо ще плаши слабите ръце.", { width: 7560 }),
          ]}),
          new TableRow({ children: [
            cell("Златно #f0d060", { width: 1800, color: "f0d060", bold: true }),
            cell("Стандартно решение / mix. Често CALL или CHECK. Ако флъфно — fold-ваш.", { width: 7560 }),
          ]}),
          new TableRow({ children: [
            cell("Амбър #ffb040", { width: 1800, color: "ffb040", bold: true }),
            cell("КАУТИОН. Conditional play (call малък / fold голям, или board threat).", { width: 7560 }),
          ]}),
          new TableRow({ children: [
            cell("Червено #ff6060", { width: 1800, color: "ff6060", bold: true }),
            cell("FOLD / give up. Не contemплирай — fold-ваш.", { width: 7560 }),
          ]}),
        ],
      }),
      p("", { after: 120 }),
      p("Простото правило: зелено = действай агресивно; златно = направи каквото казва (без overplay); амбър = бъди предпазлив; червено = fold."),

      // ── 3. PREFLOP ПРИМЕРИ ──
      p("3. Preflop — реални примери", { heading: HeadingLevel.HEADING_1 }),

      ...example(
        "3.1 Опитай: AA от UTG (стандартен 100 BB cash)",
        "Hole: A♥ A♠. Position: UTG. Stack: 100 BB. Никой не е raise-нал.",
        "RAISE (3x BB)  ·  Reason: 'AA е премиум — винаги raise.'",
        "Натискаш Raise бутона, sizing 3x BB (например 3 BB). Ако някой 3-bet-не → engine ще каже 4-BET (premium hand)."
      ),

      ...example(
        "3.2 Маргиналнa: K9o от MP",
        "Hole: K♣ 9♦. Position: MP. Stack: 80 BB.",
        "FOLD  ·  Reason: 'K9o не е в opening рейнджа от MP.'",
        "Fold-ваш. Не call-ваш — engine-ът знае, че K9o от ранна позиция е -EV дори ако никой не е raise-нал."
      ),

      ...example(
        "3.3 Short stack push: TT от BTN @ 12 BB",
        "Hole: T♥ T♦. Position: BTN. Stack: 12 BB.",
        "ALL-IN (push)  ·  Reason: 'Stack 12BB ≤ 15 → push/fold mode. TT в push range от BTN.'",
        "Натискаш All-In. На <15 BB не правиш raise за post-flop play; shove-ваш и приемаш variance."
      ),

      ...example(
        "3.4 Short stack fold: 87s от UTG @ 14 BB",
        "Hole: 8♠ 7♠. Position: UTG. Stack: 14 BB.",
        "FOLD  ·  Reason: '87s извън push range. Stack 14BB ≤ 15 → push/fold mode.'",
        "Fold-ваш. На shallow stack нямаш implied odds да играеш SC от EP."
      ),

      ...example(
        "3.5 Facing 3-bet с QQ",
        "Hole: Q♥ Q♦. Position: CO. Стандартно отвори с Raise. BTN го 3-bet-ва.",
        "4-BET (mixed) или CALL  ·  Reason: 'QQ vs 3-bet от BTN — често mixed; 4-bet за value, готов да get-it-in.'",
        "Решаваш според стака на villain-а: ако той е 100+ BB — call (играеш постфлоп); ако ≤40 BB — 4-bet/all-in."
      ),

      // PAGE BREAK
      new Paragraph({ children: [new PageBreak()] }),

      // ── 4. POSTFLOP ПРИМЕРИ ──
      p("4. Postflop — реални примери", { heading: HeadingLevel.HEADING_1 }),

      ...example(
        "4.1 Класически value bet: TPTK на dry flop",
        "Hole: A♥ K♠. Board: A♦ 7♣ 2♥. Pos: CO. Pot: 6BB. Stack: 80BB. Не facing bet.",
        "BET 33%  ·  hero_label: 'TP A +K kicker'  ·  ТИ ~94%",
        "Bet-ваш ~2BB (33% от 6BB). Engine-ът знае, че имаш TPTK на dry борд срещу wide range — почти всичко плаща."
      ),

      ...example(
        "4.2 КАУТИОН: TP на 4-flush turn",
        "Hole: T♥ 9♣. Board: 5♥ 9♥ 3♦ 7♥. Pos: BTN vs BB. Pot: 15BB. Stack: 11BB. Facing bet 8BB.",
        "CALL малък / FOLD голям (flush заплаха)  ·  Color: амбър",
        "BB-то ти направи 8BB bet (53% pot). Engine-ът отказва commit (макар че SPR=0.7) защото имаш само middle pair с 1 heart на 4-flush board. CALL ако bet е малък (≤50% pot); FOLD ако е голям. С 1 heart имаш 9 outs към flush — на river ще видиш."
      ),

      ...example(
        "4.3 КАУТИОН: TP на 4-connected board",
        "Hole: A♣ K♦. Board: 5♥ 6♣ 7♦ 8♠. Pos: CO. Pot: 15BB. Stack: 10BB. Facing bet.",
        "CALL малък / FOLD голям (straight заплаха)  ·  Color: амбър",
        "Имаш само A-high overcards. Board има 4 connected (5-6-7-8) — всеки 4 или 9 в hole-овете на villain-а прави straight. Дори villain да е air, board-ът много often connect-ва. CALL само ако bet е tiny; иначе FOLD."
      ),

      ...example(
        "4.4 Set value bet (paired board OK когато имаш силна ръка)",
        "Hole: 7♣ 7♦. Board: 7♠ A♥ 2♦. Pos: BTN vs CO. Pot: 6BB. Stack: 80BB. Не facing bet.",
        "BET 50%  ·  hand_label: 'Сет 777'  ·  ТИ ~99%",
        "Bet 3BB (50% от 6BB). Сет на dry борд почти не губи. Build pot for stacks."
      ),

      ...example(
        "4.5 Multiway downgrade",
        "Hole: A♦ Q♦. Board: Q♠ 8♣ 4♥. Pos: CO. Pot: 9BB (3 opponents). Не facing bet.",
        "CHECK (multiway)  ·  Reason: 'TPTK multiway → не bet за value. CHECK pot control.'",
        "Имаш TPTK, но 3 opponents значи че някой често има 2pair/set. Engine-ът сваля BET до CHECK. Това е защото в multiway range advantage не работи както в HU."
      ),

      ...example(
        "4.6 Bluff catch на river с EV math",
        "Hole: A♥ K♠. Board: A♦ 7♣ 2♥ 5♠ 8♦. Pos: CO vs BTN. Pot: 10BB. Facing bet 5BB.",
        "CALL (river +EV)  ·  Reason: 'River call +EV ≈ +1.2BB. eq~62% vs needed 33%. MDF=67%.'",
        "Имаш TPTK на double-paired runout. Villain bet-на 5BB за 10BB pot (50%). Pot odds са 33% — нужно 33% equity. Engine-ът оценява, че биеш 62% от narrowed range на villain (range narrowing на river = top 35% от opening). CALL е +1.2BB EV."
      ),

      ...example(
        "4.7 River BET за value vs CHECK",
        "Hole: K♠ Q♠. Board: Q♦ 8♣ 4♥ 5♠ K♣. Pos: BTN. Pot: 10BB. Stack: 30BB. Не facing bet.",
        "BET 75% (river +EV)  ·  Reason: 'Bet +EV ≈ +4.3BB > check +6.0BB.'",
        "Имаш две двойки (К+Q). На dry runout, range advantage е твой (BTN raise-нал предfлоп). EV(bet) > EV(check) защото FE~30% и при call villain често с по-слаб top-pair."
      ),

      ...example(
        "4.8 River FOLD по EV",
        "Hole: 7♣ 7♦. Board: A♠ K♥ 4♦ 9♠ J♣. Pos: BB vs UTG. Pot: 8BB. Facing bet 12BB (overbet).",
        "FOLD  ·  Reason: 'River fold: eq~15% < pot odds need 60%. EV(call) ≈ -7.2BB. MDF=45%.'",
        "Имаш underpair (77) на сухо runout с overcard A-K-J. Villain-ът overbet-ва river — типично polarised range (nuts или bluff, but overbet с UTG range е скоро винаги value). EV(call) силно отрицателен. FOLD без угризения."
      ),

      // ── 5. SPECIAL MARKERS ──
      p("5. Когато има warning markers", { heading: HeadingLevel.HEADING_1 }),
      p("Engine-ът добавя [annotations] в reason-а когато контекстът е специален. Виждаш ги в скоби."),

      p("[Multiway X опонента]", { heading: HeadingLevel.HEADING_2 }),
      p("Какво значи: 2+ active opponents в pot-а. Equity-то ти е по-ниско, защото повече hands биха пресекли борда."),
      p("Действие: ", { bold: true, after: 40 }),
      bullet("Не bluff-вай (FE на villain-ите събрана е малко)"),
      bullet("Не правиш thin value bets (само nuts/sets/2pair+ за value)"),
      bullet("TP/overpair → check-call max 1 улица"),

      p("[SPR=X commit zone]", { heading: HeadingLevel.HEADING_2 }),
      p("Какво значи: Stack/pot < 3. Малък stack относно пота — TP+ е stack-off ready."),
      p("Действие: ", { bold: true, after: 40 }),
      bullet("С TP+ — готов за all-in"),
      bullet("С draws — semi-bluff агресивно (имаш fold equity + equity)"),
      bullet("Pot-control с marginal не работи — pot ще влезе"),

      p("[Flush заплаха / Straight заплаха / Boat заплаха]", { heading: HeadingLevel.HEADING_2 }),
      p("Какво значи: Board-ът показва клас, който често бие hero range-а."),
      p("Действие: ", { bold: true, after: 40 }),
      bullet("С TP/2pair → CALL малък bet (bluff-catch); FOLD на голям bet"),
      bullet("С made flush/straight/set/2pair+ → engine не downgrade-ва (играй обикновено)"),
      bullet("Не committ-вай stack-а само с pair срещу натиск"),

      p("[stack=18BB → short]", { heading: HeadingLevel.HEADING_2 }),
      p("Какво значи: Под 25 BB ти играеш по-tight; под 15 BB — push/fold."),
      p("Действие: открий по-tight; commit fully когато играеш."),

      // PAGE BREAK
      new Paragraph({ children: [new PageBreak()] }),

      // ── 6. ИЗПОЛЗВАЙ DECISION STRIP-А ──
      p("6. Decision strip — какво да гледаш", { heading: HeadingLevel.HEADING_1 }),
      p("Тънкият моноспейс ред под hand label-а:"),
      code("Pot 14.2BB · Stack 80BB · SPR 5.6 · need 25% eq · MDF 67% · ТИ ~62%"),

      p("Pot / Stack / SPR", { heading: HeadingLevel.HEADING_3 }),
      p("Бърза проверка дали си в commit zone. SPR < 3 = commit; 3-6 = standard; >6 = pot control с marginal hands."),

      p("need X% eq (само при facing bet)", { heading: HeadingLevel.HEADING_3 }),
      p("Каква equity ти трябва за +EV call по pot odds. Ако твоят hand вероятно има тази equity — call-ваш; ако не — fold."),

      p("MDF X% (само на river facing bet)", { heading: HeadingLevel.HEADING_3 }),
      p("Защитна frequency — колко от твоя range трябва да continue-ва за да не позволиш automatic +EV bluff на villain. Информативно за range-балансиране, не определя конкретно решение с конкретна ръка."),

      p("ТИ ~N% (винаги)", { heading: HeadingLevel.HEADING_3 }),
      p("Approximate % от villain'ското range, който биеш в момента. Над 65% = доминираш; 35-65% = неутрално; под 35% = behind."),

      // ── 7. ТИ ИМАШ / ТЕ БИЕ ──
      p("7. ТИ ИМАШ / ТЕ БИЕ panel", { heading: HeadingLevel.HEADING_1 }),
      p("Това е peripheral info — не е primary signal. Тънка цветна ивица отляво кодира semantic strength:"),
      bulletRuns([
        { text: "Зелена ивица: ", bold: true, color: "3d8a52" },
        { text: "ТИ %% ≥ 65 — биеш по-голяма част от range-а" },
      ]),
      bulletRuns([
        { text: "Амбър ивица: ", bold: true, color: "a08040" },
        { text: "35-64% — coin-flip-ish, играй на pot odds" },
      ]),
      bulletRuns([
        { text: "Червена ивица: ", bold: true, color: "9a4a4a" },
        { text: "<35% — behind range-а, защитавай се" },
      ]),
      p("Текстът ти показва конкретно какво държиш и какво потенциално те бие. Полезно е за да видиш draw-овете включени (TPTK + NFD), и категориите threats (flush, straight). Не е заместител на action banner-а."),

      // ── 8. КОГА ДА OVERRIDE-НЕШ ──
      p("8. Кога да НЕ слушаш advisor-а", { heading: HeadingLevel.HEADING_1 }),
      p("Engine-ът е добър но има slabosti. Override-вай в тези случаи:", { after: 120 }),

      p("8.1 Когато имаш read на конкретен villain", { heading: HeadingLevel.HEADING_3 }),
      bullet("Ако знаеш че villain-ът bluff-ва често → call по-широко от engine препоръката"),
      bullet("Ако знаеш че е nit (не block bluff-ва) → fold по-широко на river"),
      bullet("Engine-ът ползва generic GTO ranges; не моделира player tendencies"),

      p("8.2 ICM в турнири (близо до bubble или payouts)", { heading: HeadingLevel.HEADING_3 }),
      bullet("Engine-ът не отчита ICM. На bubble не call-ваш всичко с +EV chip — fold-ваш по-tight"),
      bullet("Спрямо chips engine-ът е point-EV; ICM ти струва повече"),

      p("8.3 Когато OCR-ът е сгрешил карти", { heading: HeadingLevel.HEADING_3 }),
      bullet("Винаги проверявай hand label-а спрямо реалните си карти"),
      bullet("Ако engine показва 'TP K +Q kicker' но реално имаш Air → НЕ играй съвета"),
      bullet("Натисни F3 → въведи ръчно вярните карти → engine recompute-ва"),

      p("8.4 Стрес/tilt", { heading: HeadingLevel.HEADING_3 }),
      bullet("Ако губиш и хочеш revenge — engine ти препоръчва fold, изпълни fold-а"),
      bullet("Не override-вай към raise когато ти е казано да check-call"),

      p("8.5 Когато reason-а изглежда странно", { heading: HeadingLevel.HEADING_3 }),
      bullet("Ако reason-ът пише '[Multiway 5 опонента]' но реално си HU → engine е сгрешил player count"),
      bullet("Ако SPR показва огромна стойност на river при който са вкарани тонове chips → pot tracker може да under-count-ва"),
      bullet("В съмнителни случаи — играй по интуиция, не по UI"),

      // ── 9. ЧЕСТИ ГРЕШКИ ──
      p("9. Чести грешки на потребителите", { heading: HeadingLevel.HEADING_1 }),

      p("Грешка 1: Гледаш само ТИ ИМАШ / ТЕ БИЕ", { heading: HeadingLevel.HEADING_3 }),
      p("Зелено там НЕ значи задължително да bet-ваш. Action banner-а може да каже CHECK (multiway pot control). Action banner-а е primary."),

      p("Грешка 2: Bet-ваш по 'BET' дори когато е amber 'CHECK (flush заплаха)'", { heading: HeadingLevel.HEADING_3 }),
      p("Threat warnings променят action — чети целия action текст, не само първата дума."),

      p("Грешка 3: Игнорираш sizing", { heading: HeadingLevel.HEADING_3 }),
      p("Engine казва 'BET 33%' не 'BET 75%'. Различни sizing-и target-ват различни villain ranges. Тънък value bet с 33% получава calls от middle pair; 75% pot ги плаши."),

      p("Грешка 4: Auto-pilot без четене на reason при amber/червено", { heading: HeadingLevel.HEADING_3 }),
      p("На amber/червен action — задължително прочитай reason-а. Често има специфичен трик ('CALL малък / FOLD голям' значи че имаш condition-based действие)."),

      p("Грешка 5: Не override-ваш когато OCR е сгрешил", { heading: HeadingLevel.HEADING_3 }),
      p("Винаги cross-check hand label с реалните си карти преди голям commit."),

      // ── 10. ЕДНОРЕДОВКА ЗА БЪРЗО ИЗПЪЛНЕНИЕ ──
      p("10. TL;DR — едноредовки", { heading: HeadingLevel.HEADING_1 }),
      bullet("Зелено action banner → действай агресивно (bet/raise/all-in)"),
      bullet("Златно → стандартно решение (call/check)"),
      bullet("Амбър → conditional (read text внимателно)"),
      bullet("Червено → fold"),
      bullet("Multiway warning → не bluff, само value-heavy"),
      bullet("Threat warning (flush/straight/boat) → не committ pair/2pair"),
      bullet("SPR < 3 + TP+ → готов за all-in"),
      bullet("Cross-check hand label vs твоите карти преди commit"),
      bullet("Reason-ът обяснява защо — чети при съмнения"),

      p("", { after: 200 }),
      p("— край на ръководството —", {
        align: AlignmentType.CENTER, italics: true, color: "999999", size: 20, before: 400,
      }),
    ],
  }],
});

Packer.toBuffer(doc).then(buf => {
  const out = "C:\\Users\\Admin\\claude\\docs\\Poker_Advisor_Play_Guide_BG.docx";
  fs.writeFileSync(out, buf);
  console.log("Wrote", out, "size:", buf.length, "bytes");
});
