"""
Poker SRP OOP Strategy Tool — Preflop + Postflop (v4 — Upswing Pro)
Базирано на:
  - upswingpoker.com/continuation-bet-c-bet-strategy-position/
  - upswingpoker.com/bet-size-strategy-tips-rules/  (8 правила)
  - upswingpoker.com/3-concepts-shape-postflop-strategy/
  - upswingpoker.com/3-reasons-solvers-check-top-pair/
  - upswingpoker.com/river-poker-strategy-tips/
  - upswingpoker.com/implied-odds-poker-strategy/
  - upswingpoker.com/fold-equity/
  - upswingpoker.com/floating-poker-float-strategy/
  - upswingpoker.com/paired-flops-preflop-raiser/
  - upswingpoker.com/4-bet-size-strategy/
  + Стандартни 6-max cash preflop рейнджове.
"""

import tkinter as tk

# ─── Константи ────────────────────────────────────────────────────────────────
RANKS = ['A','K','Q','J','T','9','8','7','6','5','4','3','2']
SUITS = ['s','h','d','c']
RV = {'2':0,'3':1,'4':2,'5':3,'6':4,'7':5,'8':6,'9':7,'T':8,'J':9,'Q':10,'K':11,'A':12}
SYM = {'h':'♥','d':'♦','c':'♣','s':'♠'}
SCLR = {'h':'#e83030','d':'#3080e0','c':'#30b050','s':'#222222'}

# ─── Draw outs (стандартни покер аути) ────────────────────────────────────────
OUTS_FD          = 9   # flush draw: 13 - 4 seen = 9
OUTS_OESD        = 8   # open-ended straight draw: 4+4
OUTS_GUTSHOT     = 4   # gutshot straight draw: 4 ranks
OUTS_BFD         = 1   # backdoor flush draw: heuristic value (не реални)
OUTS_SET         = 2   # set out от pair: 2 оставащи оф цялото тесте
OUTS_OVERCARD    = 3   # overcard → pair: 3 оставащи

# ─── SPR buckets (Upswing commit vs deep stack) ───────────────────────────────
# SPR = stack / pot при започване на улицата.
# < 3   → "commit zone": top pair+ обикновено е all-in ready
# 3-6   → "standard":    по подразбиране стойностен бет, call с pot odds
# 6-12  → "cautious":    нужна по-силна ръка за stack-off (2pair+, силен draw)
# > 12  → "deep":        nut hands / sets / 2pair+ за stacks; TP = pot-control
SPR_COMMIT       = 3.0
SPR_STANDARD_MAX = 6.0
SPR_CAUTIOUS_MAX = 12.0

# ─── Pot odds thresholds (за call решения) ────────────────────────────────────
# Upswing: 33% пот бет → нужни ~20% equity; 66% пот → 28%; pot-size → 33%.
BET_SMALL  = 0.33
BET_MED    = 0.50
BET_LARGE  = 0.66
BET_POT    = 1.00
BET_OVER   = 1.25

# ─── Bet sizing defaults (Upswing 8 Rules) ────────────────────────────────────
FLOP_DRY_PCT        = 0.30  # dry rainbow низак/среден борд
FLOP_WET_PCT        = 0.70  # connected/two-tone/mono
FLOP_PAIRED_PCT     = 0.30  # paired борд — Upswing: малко но често
FLOP_HIGHDRY_PCT    = 0.33  # A/K high dry — nut advantage → малко, висока честота
FLOP_MEDIUM_PCT     = 0.55  # semi-wet
FLOP_OTHER_PCT      = 0.40  # fallback
TURN_DRY_PCT        = 0.60
TURN_WET_PCT        = 0.70
RIVER_POLAR_PCT     = 0.75  # polarized (Upswing: 66-100%)


# ─── Hand notation ────────────────────────────────────────────────────────────
def hand_name(h1, h2):
    r1, s1 = h1
    r2, s2 = h2
    v1, v2 = RV[r1], RV[r2]
    if v1 < v2:
        r1, r2 = r2, r1
        s1, s2 = s2, s1
    if r1 == r2:
        return f"{r1}{r2}"
    st = 's' if s1 == s2 else 'o'
    return f"{r1}{r2}{st}"


# ─── Preflop рейнджове (6-max 100bb cash) ─────────────────────────────────────
# Формат: за всяка позиция, min kicker ранг за suited/offsuit от всеки high card
# None = не отваряй с тази комбинация

def _build_open_ranges():
    """Връща {pos: set_of_hand_names}.

    Ranges базирани на modern GTO solutions (6-max 100bb cash, rake-adjusted):
      - UTG:  ~15% (22+, A2s+, KTs+, QTs+, J9s+, T9s, suited connectors 65s+, AJo+, KQo)
      - MP:   ~19% (22+, A2s+, K8s+, Q9s+, J9s+, T9s, 87s+, ATo+, KJo+)
      - CO:   ~27% (22+, A2s+, K5s+, Q7s+, J8s+, T8s+, 97s+, 65s+, A9o+, KTo+, QTo+)
      - BTN:  ~45% (22+, A2s+, K2s+, Q4s+, J6s+, T7s+, 96s+, 85s+, 75s+, 64s+, 53s+,
                    A2o+, K8o+, Q9o+, J9o+, T9o)
      - SB:   ~35% (similar BTN но tighter; RFI vs BB defend)
    """
    # Дефинираме: (min_pair_rank, suited_dict, offsuit_dict)
    # suited_dict: high_card -> min_kicker_rank_value
    # offsuit_dict: same
    defs = {
        # UTG — 15% RFI (tight, EP range advantage)
        'UTG': {
            'pairs': 0,  # 22+
            's': {'A':0,'K':RV['T'],'Q':RV['T'],'J':RV['9'],'T':RV['8'],'9':RV['7'],'8':RV['7'],'7':RV['5'],'6':RV['5']},
            'o': {'A':RV['J'],'K':RV['Q']}
        },
        # MP — 19% RFI
        'MP': {
            'pairs': 0,
            's': {'A':0,'K':RV['8'],'Q':RV['9'],'J':RV['9'],'T':RV['8'],'9':RV['7'],'8':RV['7'],'7':RV['5'],'6':RV['4']},
            'o': {'A':RV['T'],'K':RV['J']}
        },
        # CO — 27% RFI
        'CO': {
            'pairs': 0,
            's': {'A':0,'K':RV['5'],'Q':RV['7'],'J':RV['8'],'T':RV['8'],'9':RV['7'],'8':RV['6'],'7':RV['5'],'6':RV['4'],'5':RV['3']},
            'o': {'A':RV['9'],'K':RV['T'],'Q':RV['T'],'J':RV['T']}
        },
        # BTN — 45% RFI (wide, позиция + rake)
        'BTN': {
            'pairs': 0,
            's': {'A':0,'K':0,'Q':RV['4'],'J':RV['6'],'T':RV['7'],'9':RV['6'],'8':RV['5'],'7':RV['5'],'6':RV['4'],'5':RV['3'],'4':RV['3']},
            'o': {'A':0,'K':RV['8'],'Q':RV['9'],'J':RV['9'],'T':RV['9'],'9':RV['8']}
        },
        # SB — 25-28% RFI (tightened: GTO prefers 3-bet or fold).
        # Премахнахме marginal offsuit hands (A3o-A8o, K9o, QTo, JTo, T9o) —
        # тези са -EV cold calls/opens от SB защото BB ще squeeze често.
        # Suited range остава широка (добра playability 3-bet pot).
        'SB': {
            'pairs': 0,
            's': {'A':0,'K':RV['5'],'Q':RV['7'],'J':RV['8'],'T':RV['8'],'9':RV['7'],'8':RV['6'],'7':RV['5'],'6':RV['4'],'5':RV['3']},
            'o': {'A':RV['9'],'K':RV['T'],'Q':RV['J']}
        },
    }
    ranges = {}
    for pos, d in defs.items():
        hands = set()
        # Pairs
        for r in RANKS:
            if RV[r] >= d['pairs']:
                hands.add(f"{r}{r}")
        # Suited
        for high, min_kicker in d['s'].items():
            hv = RV[high]
            for r in RANKS:
                rv = RV[r]
                if rv < hv and rv >= min_kicker:
                    hands.add(f"{high}{r}s")
        # Offsuit
        for high, min_kicker in d['o'].items():
            hv = RV[high]
            for r in RANKS:
                rv = RV[r]
                if rv < hv and rv >= min_kicker:
                    hands.add(f"{high}{r}o")
        ranges[pos] = hands
    return ranges

OPEN_RANGES = _build_open_ranges()

# 3-bet рейнджове (vs open raise) — solver-aligned, 6-max cash
THREEBET_ALWAYS = {'AA','KK','QQ','AKs','AKo'}
THREEBET_VALUE  = {'JJ','TT','AQs','AQo','AJs','KQs'}
THREEBET_BLUFF  = {'A5s','A4s','A3s','A2s','K9s','Q9s','J9s','T9s','98s','87s','76s'}

# 4-bet рейнджове (когато hero е open-raiser и го 3-betват)
# Value — винаги 4-bet for value, готови да get-it-in срещу 5-bet
FOURBET_VALUE = {'AA','KK','AKs'}
# Bluff — Axs блокери (Ace blocks AA/AK), suited wheelers
FOURBET_BLUFF = {'A5s','A4s','A3s','A2s'}
# Mixed — понякога 4-bet, понякога call depending on position & sizing
FOURBET_MIXED = {'QQ','JJ','AKo','AQs'}

# Call vs raise (ако не 3-betваш)
CALL_STRONG = {'99','88','77','66','55','44','33','22',
               'ATs','A9s','A8s','A7s','A6s',
               'KJs','KTs','K9s','QJs','QTs','JTs','T9s','98s','87s','76s','65s','54s',
               'AJo','ATo','KQo','KJo','QJo','JTo'}

# Call vs 3-bet (когато hero е open-raiser) — IP focus
# QQ/JJ/AK често mixed (call vs 4-bet); тези са чист call
CALL_VS_3BET_IP = {'TT','99','88','77','66','55',
                   'AQs','AJs','ATs','KQs','KJs','QJs','JTs','T9s','98s','87s','76s',
                   'AQo','KQo'}
# OOP call vs 3-bet е много по-тесен (само premium + middle pairs)
CALL_VS_3BET_OOP = {'TT','99','AQs','AJs','KQs','JJ'}


# ─── Preflop анализ ───────────────────────────────────────────────────────────
def preflop_analyze(hole, hero_pos=None, facing_raise=False, raiser_pos=None,
                    facing_3bet=False, three_bettor_pos=None):
    hn = hand_name(hole[0], hole[1])
    is_suited = hn.endswith('s')
    is_pair = len(hn) == 2

    if not hero_pos:
        # Без позиция — даваме обща оценка
        tier = _hand_tier(hn)
        if tier == 1:
            return dict(action="RAISE", color="#60ff60", hand=hn,
                        reason="Премиум ръка — винаги raise от всяка позиция. Sizing: 2.5–3x BB.")
        elif tier == 2:
            return dict(action="RAISE", color="#60ff60", hand=hn,
                        reason="Силна ръка — raise от повечето позиции. Sizing: 2.5–3x BB.")
        elif tier == 3:
            return dict(action="RAISE / CALL", color="#f0d060", hand=hn,
                        reason="Играема ръка — raise от LP, call от EP. Зависи от позиция.")
        elif tier == 4:
            return dict(action="ЗАВИСИ", color="#ffb040", hand=hn,
                        reason="Маргинална ръка — само от BTN/CO/SB. Fold от EP.")
        else:
            return dict(action="FOLD", color="#ff6060", hand=hn,
                        reason="Слаба ръка — fold от повечето позиции.")

    if facing_3bet:
        return _vs_3bet(hn, hero_pos, three_bettor_pos)
    if facing_raise:
        return _vs_raise(hn, hero_pos, raiser_pos)
    else:
        return _rfi(hn, hero_pos)

def _hand_tier(hn):
    if hn in THREEBET_ALWAYS: return 1
    if hn in THREEBET_VALUE: return 2
    if hn in CALL_STRONG: return 3
    # Check opening ranges — if in CO+ range, tier 4
    if hn in OPEN_RANGES.get('CO', set()): return 4
    if hn in OPEN_RANGES.get('BTN', set()): return 4
    return 5

def _rfi(hn, pos):
    """Raise First In — ти си пръв и решаваш дали да отвориш."""
    if pos == 'BB':
        return dict(action="(BB — чакаш)", color="#f0d060", hand=hn,
                    reason="Ти си Big Blind — чакаш действие от другите.")

    rng = OPEN_RANGES.get(pos, set())
    if hn in rng:
        sizing = "2.5x BB" if pos in ('BTN','SB') else "3x BB"
        if pos == 'SB':
            sizing = "3x BB (vs BB)"
        return dict(action=f"RAISE ({sizing})", color="#60ff60", hand=hn,
                    reason=f"{hn} е в opening рейнджа от {pos}. Raise {sizing}.")
    else:
        # Check if it's close to the range
        for wider_pos in ['MP','CO','BTN']:
            if hn in OPEN_RANGES.get(wider_pos, set()):
                return dict(action="FOLD", color="#ff6060", hand=hn,
                            reason=f"{hn} е прекалено слаба за {pos}. Би играл от {wider_pos}+.")
        return dict(action="FOLD", color="#ff6060", hand=hn,
                    reason=f"{hn} не е в opening рейнджа от {pos}. Fold.")

def _vs_raise(hn, hero_pos, raiser_pos):
    """Facing an open raise. Upswing 3-bet/call/fold logic.

    SPECIAL CASE — SB vs open: BB behind still има възможност да squeeze,
    което прави всички cold-call-ове -EV извън премиум (добре documented leak).
    SB стратегия: 3-bet или fold — никога cold call.
    """
    raiser = raiser_pos or "?"
    # IP vs OOP за sizing (Upswing: 3x IP, 4x OOP)
    hero_ip = _is_ip(hero_pos, raiser_pos)
    sizing_3b = "3x raise (IP)" if hero_ip else "4x raise (OOP)"

    # ── SB-специфична логика: 3-bet или fold, НИКАКВИ cold calls ──
    if hero_pos == 'SB':
        if hn in THREEBET_ALWAYS:
            return dict(action="3-BET", color="#00e676", hand=hn,
                        reason=f"{hn} от SB vs {raiser} — 3-bet value. "
                               f"Sizing: {sizing_3b}. Get-it-in готов срещу 4-bet.")
        if hn in THREEBET_VALUE:
            return dict(action="3-BET", color="#60ff60", hand=hn,
                        reason=f"{hn} от SB vs {raiser} — 3-bet за стойност. "
                               f"Sizing: {sizing_3b}. SB играе 3-bet or fold.")
        if hn in THREEBET_BLUFF:
            return dict(action="3-BET (bluff)", color="#f0d060", hand=hn,
                        reason=f"{hn} от SB vs {raiser} — 3-bet bluff с blocker. "
                               f"Sizing: {sizing_3b}. Cold call от SB е -EV (BB squeeze-ва).")
        # Всичко друго — fold. SB cold call = -EV leak.
        return dict(action="FOLD", color="#ff6060", hand=hn,
                    reason=f"{hn} от SB vs {raiser} — FOLD. "
                           f"SB cold call е documented -EV leak (BB squeeze frequency + OOP в целия pot). "
                           f"SB стратегия: 3-bet или fold.")

    # 3-bet always (премиум)
    if hn in THREEBET_ALWAYS:
        return dict(action="3-BET", color="#00e676", hand=hn,
                    reason=f"{hn} — винаги 3-bet vs {raiser}. Sizing: {sizing_3b}. 4-bet shove при re-raise.")

    # 3-bet value (силни)
    if hn in THREEBET_VALUE:
        if raiser_pos in ('UTG','MP'):
            return dict(action="3-BET / CALL", color="#60ff60", hand=hn,
                        reason=f"{hn} vs {raiser} (EP тесен рейндж) — 3-bet {sizing_3b} или call за implied odds.")
        return dict(action="3-BET", color="#60ff60", hand=hn,
                    reason=f"{hn} vs {raiser} (LP) — 3-bet {sizing_3b} за стойност.")

    # 3-bet bluff (Upswing: Axs блокери, suited конектори от blinds)
    if hn in THREEBET_BLUFF:
        if hero_pos in ('BB','SB'):
            return dict(action="3-BET (bluff)", color="#f0d060", hand=hn,
                        reason=f"{hn} — 3-bet bluff от blinds vs {raiser}. Sizing: {sizing_3b}. "
                               f"Блокира Ax ръце, добра equity при call.")
        if hero_ip:
            return dict(action="CALL", color="#f0d060", hand=hn,
                        reason=f"{hn} — call IP vs {raiser}. Implied odds + добра постфлоп играемост.")
        return dict(action="3-BET / FOLD", color="#f0d060", hand=hn,
                    reason=f"{hn} — 3-bet bluff или fold OOP vs {raiser}. Не е добра за call OOP (трудна постфлоп).")

    # Calling range — implied odds, позиция, floating potential
    if hn in CALL_STRONG:
        if hero_ip:
            return dict(action="CALL", color="#f0d060", hand=hn,
                        reason=f"{hn} IP vs {raiser} — call. Позиционно предимство + implied odds.")
        elif hero_pos == 'BB':
            return dict(action="CALL", color="#f0d060", hand=hn,
                        reason=f"{hn} BB vs {raiser} — call. Добра цена (вече имаш 1BB в пота).")
        elif raiser_pos in ('CO','BTN'):
            return dict(action="CALL / 3-BET", color="#f0d060", hand=hn,
                        reason=f"{hn} vs {raiser} (LP, широк рейндж) — call или 3-bet light.")
        else:
            return dict(action="FOLD", color="#ff6060", hand=hn,
                        reason=f"{hn} OOP vs {raiser} (EP) — fold. Лоши implied odds + reverse implied odds.")

    # Маргинални ръце — IP спрямо позиция
    if hn in OPEN_RANGES.get('BTN', set()):
        if hero_ip:
            return dict(action="CALL (маргинално)", color="#ffb040", hand=hn,
                        reason=f"{hn} IP vs {raiser} — маргинален call. Float при добър борд.")
        return dict(action="FOLD", color="#ff6060", hand=hn,
                    reason=f"{hn} OOP vs {raiser} — fold. Reverse implied odds доминират.")

    return dict(action="FOLD", color="#ff6060", hand=hn,
                reason=f"{hn} — fold. Няма equity vs рейнджа на {raiser}.")


def _vs_3bet(hn, hero_pos, three_bettor_pos):
    """Hero open-raise-на и го 3-bet-ват. Решение: 4-bet value / 4-bet bluff / call / fold.

    Solver принципи:
    - 4-bet value = AA/KK/AKs (винаги), понякога QQ/AKo според позиция на 3-bettor
    - 4-bet bluff = Axs (блокери на AA/AK) за polarization
    - Call IP с middle pairs, AQ, broadway suited — имплайд оддс + позиция
    - Call OOP много по-тесен — OOP е губещо в 3-bet pot-ове
    - Sizing: ~2.2x 3-bet IP, ~2.5x 3-bet OOP
    """
    threebettor = three_bettor_pos or "?"
    hero_ip = _is_ip(hero_pos, three_bettor_pos)
    sizing_4b = "2.2x 3-bet (IP)" if hero_ip else "2.5x 3-bet (OOP)"

    # 4-bet value — винаги
    if hn in FOURBET_VALUE:
        return dict(action="4-BET", color="#00e676", hand=hn,
                    reason=f"{hn} — 4-bet value vs 3-bet от {threebettor}. Sizing: {sizing_4b}. "
                           f"Готов си да get-it-in срещу 5-bet.")

    # 4-bet bluff — Axs блокери, polarization
    if hn in FOURBET_BLUFF:
        if hero_ip:
            return dict(action="4-BET (bluff) / FOLD", color="#f0d060", hand=hn,
                        reason=f"{hn} — 4-bet bluff vs {threebettor}. Axs блокер намалява AA/AK комбосите. "
                               f"Sizing: {sizing_4b}. Fold vs 5-bet.")
        return dict(action="FOLD", color="#ff6060", hand=hn,
                    reason=f"{hn} OOP vs 3-bet — fold. 4-bet bluff OOP е -EV в повечето спотове.")

    # Mixed — 4-bet value или call (според позиция на 3-bettor)
    if hn in FOURBET_MIXED:
        # vs blind 3-bet: по-често 4-bet (широк range на blinds)
        if three_bettor_pos in ('SB','BB'):
            return dict(action="4-BET / CALL", color="#60ff60", hand=hn,
                        reason=f"{hn} vs {threebettor} 3-bet — 4-bet за стойност срещу широк blind range, "
                               f"или call IP. Sizing: {sizing_4b}.")
        # vs EP/MP 3-bet — тесен value range, по-често call
        return dict(action="CALL / 4-BET", color="#60ff60", hand=hn,
                    reason=f"{hn} vs {threebettor} 3-bet — call IP (добра realизация), "
                           f"или 4-bet mix. Внимавай с QQ/JJ срещу KK+.")

    # Call vs 3-bet
    call_range = CALL_VS_3BET_IP if hero_ip else CALL_VS_3BET_OOP
    if hn in call_range:
        if hero_ip:
            return dict(action="CALL", color="#f0d060", hand=hn,
                        reason=f"{hn} IP vs 3-bet от {threebettor} — call. Позиция + implied odds с set/straight potential. "
                               f"Не stack-offай с TP на сух борд.")
        return dict(action="CALL", color="#f0d060", hand=hn,
                    reason=f"{hn} OOP vs 3-bet от {threebettor} — call внимателно. "
                           f"OOP в 3-bet pot е труден — играй pot-control.")

    # Всичко останало — fold
    return dict(action="FOLD", color="#ff6060", hand=hn,
                reason=f"{hn} vs 3-bet от {threebettor} — fold. Не е достатъчно силна за call/4-bet в 3-bet pot.")


def _is_ip(hero_pos, villain_pos=None):
    """Дали hero е IP спрямо villain.

    Postflop action order: SB → BB → UTG → MP → CO → BTN (BTN действа последен).
    Ако villain_pos не е зададен, използваме approximation по hero_pos:
      BTN винаги IP, SB/BB винаги OOP, останалите — вероятностно.
    """
    # Heuristic когато нямаме villain position
    if not villain_pos:
        if hero_pos == 'BTN':
            return True
        if hero_pos in ('SB', 'BB'):
            return False
        # CO е IP срещу повечето villain (BTN е рядко), UTG/MP обикновено OOP
        return hero_pos == 'CO'

    if not hero_pos:
        return True

    # Postflop order: действа първи OOP
    postflop_order = {'SB': 0, 'BB': 1, 'UTG': 2, 'MP': 3, 'CO': 4, 'BTN': 5}
    h = postflop_order.get(hero_pos, 3)
    v = postflop_order.get(villain_pos, 3)
    return h > v


def texture_tags(bi):
    """Връща списък от текстови tag-ове за board texture (напр. ['LOW', 'Rainbow'])."""
    tags = []
    if bi['is_low']: tags.append('LOW')
    elif bi['is_mid']: tags.append('MID')
    else: tags.append('HIGH')
    if bi['is_mono']: tags.append('MONO!')
    elif bi['is_two_tone']: tags.append('2-tone')
    else: tags.append('Rainbow')
    if bi['is_paired']: tags.append('Paired')
    if bi['is_connected']: tags.append('Connected')
    if bi['is_dry']: tags.append('Dry')
    return tags


# ─── Борд текстура ───────────────────────────────────────────────────────────
def board_info(board):
    ranks = sorted([RV[c[0]] for c in board], reverse=True)
    suits = [c[1] for c in board]
    top = ranks[0]
    n = len(board)
    unique_ranks = len(set(ranks))
    unique_suits = len(set(suits))
    # is_connected: check consecutive pairs
    connected = all(ranks[i]-ranks[i+1] <= 2 for i in range(n-1)) if n >= 2 else False
    return dict(
        top=top, ranks=ranks, suits=suits,
        is_low=top <= RV['9'], is_mid=RV['9'] < top <= RV['J'], is_high=top >= RV['Q'],
        is_mono=unique_suits == 1,
        is_two_tone=unique_suits == 2,
        is_rainbow=unique_suits >= 3,
        is_paired=unique_ranks < n,
        is_connected=connected,
        is_dry=unique_suits >= 3 and not connected and unique_ranks == n,
    )


# ─── Дро детекция ─────────────────────────────────────────────────────────────
def made_flush(hole, board):
    """Проверява дали имаме made flush (5+ карти от една боя, поне 1 hole card)."""
    for suit in set(c[1] for c in hole):
        cnt_hole = sum(1 for c in hole if c[1] == suit)
        cnt_board = sum(1 for c in board if c[1] == suit)
        if cnt_hole >= 1 and cnt_hole + cnt_board >= 5:
            return True
    return False

def flush_draw(hole, board):
    """Проверява за flush draw (4 карти от една боя, поне 1 hole card). Не е draw ако вече е made."""
    if made_flush(hole, board):
        return False
    for suit in set(c[1] for c in hole):
        cnt_hole = sum(1 for c in hole if c[1] == suit)
        cnt_board = sum(1 for c in board if c[1] == suit)
        if cnt_hole >= 1 and cnt_hole + cnt_board >= 4:
            return True
    return False

def backdoor_fd(hole, board):
    """Suited hole + 1 от същата боя на борда (3 total, нужни 2 повече). Само на flop."""
    if len(board) > 3:
        return False  # backdoor е релевантен само на flop
    for suit in set(c[1] for c in hole):
        cnt_hole = sum(1 for c in hole if c[1] == suit)
        cnt_board = sum(1 for c in board if c[1] == suit)
        if cnt_hole >= 2 and cnt_board == 1:
            return True
        if cnt_hole == 1 and cnt_board >= 2:
            return True
    return False

def nut_flush_draw(hole, board):
    """Имаме ли Ace от flush draw боята?"""
    if not flush_draw(hole, board):
        return False
    for suit in set(c[1] for c in hole):
        cnt = sum(1 for c in hole + board if c[1] == suit)
        if cnt >= 4:
            if any(c[0] == 'A' and c[1] == suit for c in hole):
                return True
    return False

def straight_draws(hole, board):
    """OESD и gutshot детекция с всички hole+board карти."""
    vals = sorted(set(RV[c[0]] for c in hole + board))
    if 12 in vals: vals = [-1] + vals
    oesd = gutshot = False
    for i in range(len(vals)-3):
        w = vals[i:i+4]; span = w[-1]-w[0]; u = len(set(w))
        if span == 3 and u == 4: oesd = True
        elif span <= 4 and u >= 3: gutshot = True
    return oesd, gutshot

def made_straight(hole, board):
    """Проверява за made straight (5 последователни, поне 1 hole card)."""
    all_vals = sorted(set(RV[c[0]] for c in hole + board))
    if len(all_vals) < 5:
        return False
    if 12 in all_vals:
        all_vals = [-1] + all_vals
    hole_vals_set = set(RV[c[0]] for c in hole)
    # Ace-low: hole card ace counts as -1 too
    if 12 in hole_vals_set:
        hole_vals_set.add(-1)
    for i in range(len(all_vals) - 4):
        w = all_vals[i:i+5]
        if w[-1] - w[0] == 4 and len(set(w)) == 5:
            # Поне 1 hole card трябва да участва
            if any(v in hole_vals_set for v in w):
                return True
    return False


# ─── Made hands (3 of a kind family) ────────────────────────────────────────
def made_quads(hole, board):
    """Каре (4 от един ранк). Hero допринася поне с 1 карта.

    Случаи:
      - pocket pair + 2 matching board cards (напр. 77 + 7-7-A)
      - 1 hole card + 3 matching board cards (напр. 7-K + 7-7-7-A)
    Връща (True, rank) или (False, None).
    """
    hole_ranks = [c[0] for c in hole]
    board_ranks = [c[0] for c in board]
    # Case 1: pocket pair + 2 matching board
    if hole_ranks[0] == hole_ranks[1] and board_ranks.count(hole_ranks[0]) >= 2:
        return (True, hole_ranks[0])
    # Case 2: 3-of-a-kind on board + 1 matching hole
    for hr in set(hole_ranks):
        if board_ranks.count(hr) >= 3:
            return (True, hr)
    return (False, None)


def made_full_house(hole, board):
    """Фул хаус (трипс + чифт). Hero допринася поне с 1 карта.

    Връща (True, trips_rank, pair_rank) или (False, None, None).
    Избира НАЙ-СИЛНИЯ FH (highest trips, после highest pair).

    Изключва quads (които се ловят отделно).
    """
    from collections import Counter
    hole_ranks = [c[0] for c in hole]
    board_ranks = [c[0] for c in board]
    cnt = Counter(hole_ranks + board_ranks)

    trips_candidates = sorted(
        [r for r, n in cnt.items() if n >= 3 and n < 4],
        key=lambda r: RV[r], reverse=True,
    )
    if not trips_candidates:
        return (False, None, None)

    for trips_r in trips_candidates:
        # Намираме най-силния различен ранк с поне 2 копия
        other_pairs = sorted(
            [r for r, n in cnt.items() if n >= 2 and r != trips_r],
            key=lambda r: RV[r], reverse=True,
        )
        if not other_pairs:
            continue
        pair_r = other_pairs[0]
        # Hero трябва да допринася (или с trips_r или с pair_r)
        if trips_r in hole_ranks or pair_r in hole_ranks:
            return (True, trips_r, pair_r)

    return (False, None, None)


def made_trips(hole, board):
    """Trips = paired board + 1 matching hole card. Различно от set!

    Не се триггерва за:
      - pocket pair (това е set, ако match-ва борда)
      - quads/full house (обработват се преди trips)
    Връща (True, rank, kicker_rank) или (False, None, None).
    """
    from collections import Counter
    hole_ranks = [c[0] for c in hole]
    board_ranks = [c[0] for c in board]

    # Скип ако е pocket pair (set/quads/FH ще го хванат)
    if hole_ranks[0] == hole_ranks[1]:
        return (False, None, None)

    for i, hr in enumerate(hole_ranks):
        if board_ranks.count(hr) >= 2:
            kicker = hole_ranks[1 - i]
            # Проверка че не е FH: ако има друг чифт в total combo → FH
            cnt = Counter(hole_ranks + board_ranks)
            other_pairs = [r for r, n in cnt.items()
                           if n >= 2 and r != hr]
            if other_pairs:
                return (False, None, None)  # FH — не trips
            return (True, hr, kicker)

    return (False, None, None)


# ─── Класификация на hero ръката ────────────────────────────────────────────
def classify_hero_hand(hole, board):
    """Връща ('class_id', 'human_label') за hero ръката.

    class_id: 'high_card'|'pair'|'two_pair'|'trips'|'set'|'straight'|
              'flush'|'full_house'|'quads'|'straight_flush'

    human_label: човешко описание (напр. "Trips 7s + K kicker", "Сет AA",
                 "Top pair K kicker", "Overpair JJ", "Air").
    """
    if not board or len(board) < 3:
        # Preflop — само ranks
        h1, h2 = hole
        if h1[0] == h2[0]:
            return ('pair', f"Чифт {h1[0]}{h2[0]}")
        return ('high_card', f"{h1[0]}{h2[0]}{'s' if h1[1]==h2[1] else 'o'}")

    # Straight flush (rare, най-висока хитова класа над quads дори)
    if made_flush(hole, board) and made_straight(hole, board):
        # Probably SF — груба евристика, без exact 5-card eval
        return ('straight_flush', "STRAIGHT FLUSH!")

    # Quads
    has_q, qr = made_quads(hole, board)
    if has_q:
        return ('quads', f"QUADS {qr}{qr}{qr}{qr}")

    # FH
    has_fh, ft, fp = made_full_house(hole, board)
    if has_fh:
        return ('full_house', f"Boat {ft}{ft}{ft} full of {fp}{fp}")

    # Flush
    if made_flush(hole, board):
        # Намери боята
        from collections import Counter
        scnt = Counter(c[1] for c in hole + board)
        suit = max(scnt, key=scnt.get)
        return ('flush', f"FLUSH ({suit})")

    # Straight
    if made_straight(hole, board):
        return ('straight', "STRAIGHT")

    # Set
    h1, h2 = hole
    hole_ranks = [h1[0], h2[0]]
    board_ranks = [c[0] for c in board]
    if hole_ranks[0] == hole_ranks[1] and hole_ranks[0] in board_ranks:
        return ('set', f"Сет {hole_ranks[0]}{hole_ranks[0]}{hole_ranks[0]}")

    # Trips
    has_t, tr, tk = made_trips(hole, board)
    if has_t:
        return ('trips', f"Trips {tr}{tr}{tr} +{tk} kicker")

    # Two pair
    paired_with_board = [r for r in hole_ranks if r in board_ranks]
    if len(set(paired_with_board)) == 2:
        return ('two_pair', f"Две двойки ({paired_with_board[0]}+{paired_with_board[1]})")

    # Overpair / underpair (pocket pair)
    if hole_ranks[0] == hole_ranks[1]:
        pv = RV[hole_ranks[0]]
        top = max(RV[r] for r in board_ranks)
        rk = hole_ranks[0]
        if pv > top:
            return ('pair', f"Overpair {rk}{rk}")
        return ('pair', f"Underpair {rk}{rk}")

    # Pair with board
    if paired_with_board:
        rk = paired_with_board[0]
        kicker = hole_ranks[1] if hole_ranks[0] == rk else hole_ranks[0]
        top = max(RV[r] for r in board_ranks)
        if RV[rk] == top:
            return ('pair', f"TP {rk} +{kicker} kicker")
        # Mid/bot pair
        sorted_board = sorted(set(RV[r] for r in board_ranks), reverse=True)
        if len(sorted_board) >= 2 and RV[rk] == sorted_board[1]:
            return ('pair', f"Mid pair {rk} +{kicker} kicker")
        return ('pair', f"Pair {rk} +{kicker} kicker")

    # Air / overcards
    overcards = sum(1 for r in hole_ranks if RV[r] > max(RV[br] for br in board_ranks))
    if overcards == 2:
        return ('high_card', f"2 overcards ({hole_ranks[0]}{hole_ranks[1]})")
    return ('high_card', f"Air ({hole_ranks[0]}{hole_ranks[1]})")


# ─── Hand threats (за "ТЕ БИЕ" поленце) ─────────────────────────────────────
def hand_threats(hole, board, hero_class):
    """За дадена hero ръка + борд, връща списък с категории които я БИЯТ.

    hero_class: 'high_card'|'pair'|'two_pair'|'trips'|'set'|'straight'|
                'flush'|'full_house'|'quads'

    Връща list of strings — описателни prompts какво може да те бие
    с heuristic indicator на вероятност (HIGH/MID/LOW).

    Анализира борда за:
      - flush possible (≥3 от една боя на борда)
      - straight possible (3-4 connected cards на борда)
      - paired board (FH/quads possible)
      - set possible (over-pair villain hits set)

    Връща примерно: ['flush (HIGH — 3♠ на борда)',
                     'full house (MID — двойка на борда)',
                     'higher trips (LOW — board има само 7-A-7)']
    """
    from collections import Counter
    if not board or len(board) < 3:
        return []

    board_ranks = [c[0] for c in board]
    board_suits = [c[1] for c in board]
    rcnt = Counter(board_ranks)
    scnt = Counter(board_suits)

    threats = []
    hierarchy = ['high_card', 'pair', 'two_pair', 'trips', 'set',
                 'straight', 'flush', 'full_house', 'quads',
                 'straight_flush']
    hero_rank = hierarchy.index(hero_class) if hero_class in hierarchy else 0

    # Flush threat
    if hero_rank < hierarchy.index('flush'):
        max_suit = max(scnt.values())
        hero_suits = Counter(c[1] for c in hole)
        if max_suit >= 4:
            top_suit = max(scnt, key=scnt.get)
            if hero_suits.get(top_suit, 0) >= 1:
                pass  # hero вече има flush draw/made
            else:
                threats.append(f"flush (HIGH — 4 на борда)")
        elif max_suit == 3:
            top_suit = max(scnt, key=scnt.get)
            held = hero_suits.get(top_suit, 0)
            if held == 0:
                threats.append("flush (MID — 3 от боя на борда)")
            elif held == 1:
                threats.append("по-висок flush (LOW — 1 hole от боята)")

    # Straight threat
    if hero_rank < hierarchy.index('straight'):
        vals = sorted(set(RV[r] for r in board_ranks))
        if 12 in vals:
            vals = [-1] + vals
        max_run = 0
        for i in range(len(vals)):
            for j in range(i + 1, len(vals) + 1):
                w = vals[i:j]
                if len(w) >= 3 and w[-1] - w[0] <= 4:
                    max_run = max(max_run, len(w))
        if max_run >= 4:
            threats.append("straight (HIGH — 4 connected на борда)")
        elif max_run == 3:
            threats.append("straight (MID — 3 connected на борда)")

    # Full house threat (на paired борд)
    paired_board = any(n >= 2 for n in rcnt.values())
    if hero_rank < hierarchy.index('full_house') and paired_board:
        paired_ranks = [r for r, n in rcnt.items() if n >= 2]
        if hero_class in ('pair', 'two_pair', 'trips', 'set'):
            threats.append(
                f"full house (MID — paired board {paired_ranks[0]}{paired_ranks[0]})"
            )
        else:
            threats.append("full house (LOW — paired board)")

    # Quads threat (само ако борд има trips)
    if hero_rank < hierarchy.index('quads'):
        trip_ranks = [r for r, n in rcnt.items() if n >= 3]
        if trip_ranks:
            threats.append(f"quads (LOW — board има {trip_ranks[0]}{trip_ranks[0]}{trip_ranks[0]})")

    # Higher pair / overpair / 2-pair threats за weak hero
    if hero_class == 'pair':
        # Намираме top board card
        top_rv = max(RV[r] for r in board_ranks)
        top_r = next(r for r in board_ranks if RV[r] == top_rv)
        threats.append(f"top pair / overpair / 2pair / set")
    elif hero_class == 'two_pair':
        threats.append("set / higher 2pair")
    elif hero_class in ('trips', 'set'):
        # Higher trips/set
        higher_card_count = sum(1 for r in board_ranks if RV[r] > 0)  # placeholder
        threats.append("higher trips/set (rare)")

    return threats


# ─── Математика: equity и pot odds ───────────────────────────────────────────
def equity_from_outs(outs, streets_left=2):
    """Приблизителна equity от outs. Rule of 2 & 4.
    streets_left=2 → flop (turn+river), =1 → turn (river only)."""
    if streets_left >= 2:
        # По-точна формула: 1 - (47-outs)/47 * (46-outs)/46
        eq = 1 - ((47-outs)/47) * ((46-outs)/46)
    else:
        eq = outs / 46
    return min(eq, 0.99)

def pot_odds_needed(bet_pct):
    """Каква equity ти трябва за call при даден бет като % от пота.
    bet_pct: напр. 0.33 (33% пот), 0.5, 0.66, 1.0 (пот-size)."""
    return bet_pct / (1 + 2 * bet_pct)


def implied_odds(outs, pot_bb, bet_bb, effective_stack_bb, streets_left=2,
                  nut_draw=True, position_ip=True):
    """Оценка на implied odds за call на дро.

    Връща dict:
      direct_equity: pure equity от outs (0-1)
      needed: pot odds threshold
      required_future: колко BB трябва да спечелиш on future streets
      reachable_pct: каква част от remaining stack реалистично се инкасира
      verdict: 'call' / 'marginal' / 'fold'
      note: човешки обяснение
    """
    eq = equity_from_outs(outs, streets_left)
    needed = pot_odds_needed(bet_bb / pot_bb) if pot_bb > 0 else 0.5
    equity_gap = needed - eq  # колко ни липсва от pure pot odds

    if equity_gap <= 0:
        return dict(direct_equity=eq, needed=needed, required_future=0.0,
                    reachable_pct=1.0, verdict='call',
                    note=f"Direct pot odds OK: eq={eq*100:.0f}% ≥ need={needed*100:.0f}%.")

    # Implied: трябва да спечелиш ≈ bet * (gap / hit_prob) on future streets
    # hit_prob = eq (за draws основно = outs/47)
    hit_prob = max(0.05, outs / 47.0) if streets_left >= 1 else 0.01
    required_future = (equity_gap / hit_prob) * (pot_bb + bet_bb)

    # Reachable: IP nut draws реализират ~35-50% от remaining stack on hit
    # OOP non-nut: ~15-25%
    if nut_draw and position_ip:
        reachable_pct = 0.45
    elif nut_draw:
        reachable_pct = 0.30
    elif position_ip:
        reachable_pct = 0.25
    else:
        reachable_pct = 0.12

    reachable_bb = effective_stack_bb * reachable_pct
    ratio = reachable_bb / required_future if required_future > 0 else 99.0

    if ratio >= 1.3:
        verdict = 'call'
        note = f"Implied OK: нужни ~{required_future:.1f}BB бъдещо, реалистично {reachable_bb:.1f}BB."
    elif ratio >= 0.8:
        verdict = 'marginal'
        note = f"Implied маргинално: нужни {required_future:.1f}BB, реалистично {reachable_bb:.1f}BB."
    else:
        verdict = 'fold'
        note = f"Implied лош: нужни {required_future:.1f}BB но реалистично само {reachable_bb:.1f}BB."

    return dict(direct_equity=eq, needed=needed, required_future=required_future,
                reachable_pct=reachable_pct, verdict=verdict, note=note)


def check_raise_frequency(bi, hand_strength, position_ip, spr_name=None):
    """Честота на check-raise като OOP defender vs c-bet.

    Upswing концепция: check-raise-ваш повече на статични бордове с малко equity,
    по-малко на dynamic бордове (там check-call-ваш).

    Args:
      bi: board_info dict
      hand_strength: 'monster'|'strong'|'medium'|'draw'|'air'
      position_ip: True ако hero е IP (тогава няма CR, чек-beт е опция)
      spr_name: SPR bucket

    Returns:
      (freq: float 0-1, note: str)
    """
    if position_ip:
        return (0.0, "IP — CR не се прилага, chequay или бетвай сам.")

    # Commit SPR → никаква сложност, просто get-it-in
    if spr_name == 'commit':
        if hand_strength in ('monster', 'strong'):
            return (0.9, "Commit SPR — CR за stack-off.")
        return (0.0, "Commit SPR + слаба ръка — без CR.")

    # Dry бордове: ниска CR честота (villain-ът ще bet-bet-bet)
    if bi['is_dry']:
        if hand_strength == 'monster':
            return (0.35, "Dry борд — CR сетове ~35% (иначе slow-play).")
        if hand_strength == 'strong':
            return (0.15, "Dry борд — CR силни ръце рядко, обикновено call за thin value.")
        if hand_strength == 'draw':
            return (0.10, "Dry борд — малко bluff CR (villain cb-ва често, използвай това).")
        return (0.0, "")

    # Paired бордове: balancing CR по Upswing paired flops rule
    if bi['is_paired']:
        if hand_strength in ('monster', 'strong'):
            return (0.40, "Paired борд — CR силни ръце за stack-off.")
        if hand_strength == 'draw':
            return (0.15, "Paired борд — CR bluff понякога (villain cb-ва рядко).")
        return (0.0, "")

    # Wet/connected/monotone: висока CR честота с draws + монстри
    if bi['is_mono'] or bi['is_connected'] or bi['is_two_tone']:
        if hand_strength == 'monster':
            return (0.55, "Wet борд — CR монстри високо за protection + value.")
        if hand_strength == 'strong':
            return (0.30, "Wet борд — CR mid strength 30%.")
        if hand_strength == 'draw':
            return (0.30, "Wet борд — CR draws с equity (semi-bluff).")
        return (0.10, "")

    # Medium бордове
    if hand_strength == 'monster':
        return (0.40, "Medium борд — CR монстри често.")
    if hand_strength == 'draw':
        return (0.20, "Medium борд — semi-bluff CR с draws.")
    return (0.15, "")


def cbet_frequency(bi, hand_strength, position_ip, spr_name=None, num_opponents=1):
    """Честота на c-bet като PFA по board texture (Upswing Rules 3-8).

    Args:
      bi: board_info dict
      hand_strength: 'monster'|'strong'|'medium'|'draw'|'air'|'overcard'
      position_ip: True ако hero е IP
      spr_name: 'commit'|'standard'|'cautious'|'deep'|None
      num_opponents: multiway adjustment

    Returns:
      (freq: float 0-1, sizing_pct: float, note: str)

    По Upswing:
      - Dry boards (A73r): 60-70% c-bet small (25-33%)
      - Paired boards (T72): 50% c-bet small (25-33%)
      - High-card boards (AKx): 65-75% c-bet small (33%)
      - Wet dynamic (JT9, 876): 30-40% c-bet large (66-75%)
      - Monotone: 25% c-bet (много силен range)
    """
    # Multiway: с 2+ противника сваляме cbet с 40-50%
    mw_factor = 1.0
    if num_opponents >= 3:
        mw_factor = 0.3  # много намалена
    elif num_opponents == 2:
        mw_factor = 0.5

    # Monsters винаги bet (unless slow-play scenarios)
    if hand_strength == 'monster':
        return (0.95 * mw_factor, 0.66, "Монстър — винаги value bet.")

    # Paired boards — Upswing high-freq small
    if bi['is_paired']:
        if hand_strength in ('strong', 'medium'):
            return (0.65 * mw_factor, 0.33,
                    "Paired борд: cbet малък (33%) с range advantage.")
        if hand_strength == 'draw':
            return (0.50 * mw_factor, 0.33, "Paired + draw: semi-bluff small.")
        if hand_strength in ('air', 'overcard'):
            return (0.30 * mw_factor, 0.33, "Paired + air: cbet често но внимавай.")
        return (0.0, 0.33, "Paired, pot-control.")

    # Monotone — много силен mix range, малко cbet
    if bi.get('is_mono', False):
        if hand_strength == 'strong':
            return (0.40 * mw_factor, 0.50, "Monotone: cbet само strong ръце.")
        if hand_strength == 'draw':
            return (0.25 * mw_factor, 0.50, "Monotone + draw: малко cbet.")
        return (0.10 * mw_factor, 0.50,
                "Monotone: предимно check — твоят range е relatively silен.")

    # Wet connected dynamic (JT9, 876, 765) — малка cbet frequency, голямо sizing
    if bi.get('is_connected', False) and bi.get('is_two_tone', False):
        if hand_strength == 'strong':
            return (0.60 * mw_factor, 0.75, "Wet dynamic + strong: cbet голям 66-75%.")
        if hand_strength == 'draw':
            return (0.55 * mw_factor, 0.66, "Wet dynamic + draw: semi-bluff голям.")
        if hand_strength == 'medium':
            return (0.35 * mw_factor, 0.66, "Wet dynamic + medium: protect 35%.")
        # AIR or overcard on very wet → CHECK
        return (0.15 * mw_factor, 0.66,
                "Wet dynamic + air: CHECK preferred — villain ще calling stations.")

    # High-card dry (Axx, Kxx rainbow with gap)
    if bi.get('is_high', False) and bi['is_dry']:
        if hand_strength in ('strong', 'medium'):
            return (0.75 * mw_factor, 0.33,
                    "High-card dry: cbet малък 33%, висока честота (nut advantage).")
        if hand_strength == 'draw':
            return (0.60 * mw_factor, 0.33, "High-card dry + draw: semi-bluff.")
        if hand_strength in ('air', 'overcard'):
            return (0.50 * mw_factor, 0.33, "High-card dry + air: range cbet 33%.")
        return (0.30 * mw_factor, 0.33, "")

    # Generic dry board (low, rainbow, no draws)
    if bi['is_dry']:
        if hand_strength == 'strong':
            return (0.70 * mw_factor, 0.33, "Dry: cbet малък често за value.")
        if hand_strength == 'medium':
            return (0.55 * mw_factor, 0.33, "Dry + medium: cbet protect.")
        if hand_strength == 'draw':
            return (0.55 * mw_factor, 0.33, "Dry + draw: semi-bluff malko.")
        if hand_strength == 'overcard':
            return (0.45 * mw_factor, 0.33, "Dry + overcard: може да bet за fold equity.")
        if hand_strength == 'air':
            return (0.30 * mw_factor, 0.33, "Dry + air: малко bluff cbet OK.")
        return (0.0, 0.33, "")

    # Medium / two-tone non-connected
    if hand_strength == 'strong':
        return (0.55 * mw_factor, 0.50, "Medium борд + strong: cbet 50% за value.")
    if hand_strength == 'medium':
        return (0.35 * mw_factor, 0.50, "Medium + medium hand: check-call често.")
    if hand_strength == 'draw':
        return (0.45 * mw_factor, 0.50, "Medium + draw: semi-bluff 45%.")
    return (0.20 * mw_factor, 0.50, "Medium + air: CHECK най-често.")


def mdf_threshold(bet_pct):
    """Minimum Defense Frequency — колко от hero range-а трябва да продължи
    за да не се exploit-ва от villain bluff-ове.

    MDF = 1 - bet / (bet + pot_before_bet) = pot / (pot + bet)
    Примери:
      - 33% pot bet → MDF = 0.75 (защитаваш 75% от range)
      - 66% pot bet → MDF = 0.60
      - 100% pot bet → MDF = 0.50
      - 150% overbet → MDF = 0.40

    Индивидуална ръка е на ръба на MDF ако equity ≈ pot_odds_needed.
    Това е "bluff-catch" зона: имаш showdown value срещу bluff-овете
    но губиш срещу value. При MDF equity ~ 30-40% срещу balanced range.
    """
    if bet_pct <= 0:
        return 1.0
    return 1.0 / (1.0 + bet_pct)


def rio_penalty(draw_type, nut_draw, spr_name, position_ip):
    """Reverse Implied Odds penalty за не-нут draws at deep SPR.
    Връща (penalty_factor, note):
      penalty_factor = множител за equity (1.0 = няма RIO, 0.7 = тежък RIO)
    """
    # Нут дро няма RIO
    if nut_draw:
        return (1.0, "")

    # Deep/cautious SPR + OOP + non-nut = най-тежкият RIO сценарий
    if spr_name in ('deep', 'cautious') and not position_ip:
        if draw_type in ('flush_draw', 'oesd'):
            return (0.75, "RIO: не-нут дро OOP deep SPR — понякога биеш но плащаш повече при hit.")
        if draw_type == 'gutshot':
            return (0.65, "RIO тежък: non-nut gutshot OOP deep — губиш големи потове при hit.")
        if draw_type == 'top_pair_weak':
            return (0.70, "RIO: TP слаб кикер OOP deep — доминиран често, reverse implied odds.")

    # Shallow SPR или IP — по-малък RIO
    if not nut_draw and draw_type in ('flush_draw', 'oesd'):
        return (0.90, "Лек RIO: не-нут дро, внимавай при call-down.")

    return (1.0, "")

def count_outs(hand_type, draw_outs, n_overcards, hole_vals):
    """Брои ОБЩО ефективни аути (made hand improvement + draw outs).
    Връща (clean_outs, description)."""
    outs = draw_outs  # от draws (FD, OESD, gutshot, bfd)
    parts = []

    # Overcards аути (3 per overcard, но discount за доминация)
    if hand_type in ('air', 'overcard', 'gutshot_only'):
        oc_outs = n_overcards * 3
        # Discount: ако кикерът е слаб (< 8), шансът за доминация е по-голям
        low_card = min(hole_vals)
        if low_card < RV['6']:
            oc_outs = int(oc_outs * 0.5)  # тежък discount
        elif low_card < RV['8']:
            oc_outs = int(oc_outs * 0.7)
        if oc_outs > 0:
            parts.append(f"{oc_outs} overcard")
        outs += oc_outs

    if draw_outs > 0:
        parts.append(f"{draw_outs} draw")

    # Made hand аути за подобрение
    if hand_type == 'mid_pair':
        outs += 2  # set out (2 карти)
        parts.append("2 set")
    elif hand_type == 'top_pair_weak':
        outs += 0  # подобрение на кикер не е надеждно
    elif hand_type == 'underpair_close':
        outs += 2  # set outs
        parts.append("2 set")

    desc = " + ".join(parts) if parts else "0"
    return outs, desc


# ─── Позиционен модификатор (Upswing 3 концепции) ────────────────────────────
def pos_adjust(hero_pos, villain_pos, bi):
    """Upswing 3 Concepts: Positional / Range / Nut Advantage.
    cbet: колко агресивно c-bet (+2 много, -2 passive)
    bluff: колко агресивно bluff (+2 много, -2 passive)
    ip: дали hero e IP"""
    cbet = bluff = 0; note = ""
    ip = _is_ip(hero_pos, villain_pos)

    # ── 1. Positional Advantage (IP vs OOP) ──
    if ip:
        cbet += 1; bluff += 1
        note = "IP: по-агресивен."
    else:
        cbet -= 1; bluff -= 1
        note = "OOP: по-пасивен, чекваш повече."

    # ── 2. Range Advantage (EP → по-тесен, по-силен рейндж) ──
    if hero_pos in ('UTG','MP'):
        cbet += 1  # тесен = по-силен рейндж = по-агресивен
    if villain_pos in ('UTG','MP'):
        cbet -= 1  # villain има силен рейндж
        bluff -= 1

    # SB vs BB: hero рейндж е по-силен (BB дефендва широко)
    if hero_pos == 'SB' and (villain_pos == 'BB' or villain_pos is None):
        cbet += 1; bluff += 1; note = "SB vs BB: рейндж предимство."

    # ── 3. Nut Advantage (зависи от борда) ──
    # Високи борди (A/K/Q high): PFR има nut advantage
    if bi['is_high']:
        cbet += 1
    # Ниски свързани борди: caller (BB) има nut advantage (67s, 78s, 54s)
    if bi['is_connected'] and bi['is_low']:
        cbet -= 1; bluff -= 1
    # Paired борди: PFR рядко има trips, caller също → c-bet с малък sizing
    if bi['is_paired']:
        cbet += 1  # c-bet често но малко
    # Monotone: намали агресия (flush рискове)
    if bi['is_mono']:
        cbet -= 1; bluff -= 1
    # Dry low борди: PFR c-bet малко но често
    if bi['is_dry'] and bi['is_low']:
        cbet += 1

    return dict(cbet=max(-2,min(2,cbet)), bluff=max(-2,min(2,bluff)), note=note, ip=ip)


# ─── SPR (Stack-to-Pot Ratio) ─────────────────────────────────────────────────
def spr_bucket(spr):
    """Класифицира SPR в bucket за decision making.

    Връща (name, note):
      'commit'   — SPR < 3: TP+ обикновено е stack-off. Мини-raises = all-in.
      'standard' — 3-6: стандартно cash SPR. Value bet, call с pot odds.
      'cautious' — 6-12: нужна по-силна ръка за stacks; TP = pot control.
      'deep'     — > 12: сетове/2pair+ за stacks. TP = 1-2 улици value max.
    """
    if spr is None:
        return (None, "")
    if spr < SPR_COMMIT:
        return ('commit', f"SPR={spr:.1f} commit zone: готов си да stack-ofнеш с TP+.")
    if spr < SPR_STANDARD_MAX:
        return ('standard', f"SPR={spr:.1f} стандартно: pot odds и value bet по теория.")
    if spr < SPR_CAUTIOUS_MAX:
        return ('cautious', f"SPR={spr:.1f} по-дълбоко: TP играй pot-control, не stack-offай.")
    return ('deep', f"SPR={spr:.1f} deep: само nuts/sets/2pair+ за stacks. TP = 1 улица.")


# ─── Postflop анализ (v4 — с SPR) ─────────────────────────────────────────────
def postflop_analyze(hole, board, facing_bet=False, hero_pos=None, villain_pos=None,
                     stack_bb=None, pot_bb=None, num_opponents=1):
    """Postflop decision engine.

    Args:
        hole: 2 hole cards [(rank, suit), ...]
        board: 3-5 board cards
        facing_bet: True ако villain е заложил (не сме PFA)
        hero_pos, villain_pos: 'UTG'|'MP'|'CO'|'BTN'|'SB'|'BB'
        stack_bb: ефективен stack на hero в BB (effective = min(hero, villain))
        pot_bb: текущ pot в BB (преди текущия бет, ако facing_bet=True)
        num_opponents: брой активни противници (1 = HU, 2+ = multiway)

    Ако stack_bb и pot_bb са дадени, SPR awareness се включва:
      commit / standard / cautious / deep → adjust stack-off logic.
    Multiway (num_opponents >= 2):
      - Draws намаляват стойност (някой има better draw или made hand)
      - TP/overpair се играят pot-control (по-често check-call)
      - Bluff c-bets почти spадат до 0; само value bet-ове
    """
    h1, h2 = hole
    bi = board_info(board)
    top = bi['top']
    board_ranks = [c[0] for c in board]
    hole_ranks = [h1[0], h2[0]]
    hole_vals = sorted([RV[h1[0]], RV[h2[0]]], reverse=True)

    # Street detection
    streets_left = max(0, 2 - (len(board) - 3))  # flop=2, turn=1, river=0
    street_name = {3: 'flop', 4: 'turn', 5: 'river'}.get(len(board), 'flop')
    is_river = streets_left == 0

    # Hero hand classification + threats (за "ТИ ИМАШ / ТЕ БИЕ" поленце)
    hero_class, hero_label = classify_hero_hand(hole, board)
    hero_threats = hand_threats(hole, board, hero_class)

    # SPR изчисление + bucketing (ако имаме stack/pot info)
    spr_val = None
    if stack_bb is not None and pot_bb is not None and pot_bb > 0:
        spr_val = max(0.0, float(stack_bb) / float(pot_bb))
    spr_name, spr_note = spr_bucket(spr_val)

    # Multiway adjustment: когато има 2+ противника, equity-то ни пада
    # и нужно е по-тесен селект. Връщаме note + флагове.
    is_multiway = num_opponents >= 2
    mw_note = ""
    if is_multiway:
        mw_note = f"Multiway ({num_opponents} опонента): TP = 1 улица, draws downgrade, без bluff c-bet."

    # Draw detection — no draws on river
    if is_river:
        fd = nfd = bfd = oesd = gutshot = False
    else:
        fd = flush_draw(hole, board)
        nfd = nut_flush_draw(hole, board)
        bfd = backdoor_fd(hole, board)
        oesd, gutshot = straight_draws(hole, board)

    # Made hand detection (works on all streets)
    has_made_flush = made_flush(hole, board)
    has_made_straight = made_straight(hole, board)

    fs = bi['ranks']  # sorted desc
    has_ace = 'A' in hole_ranks
    has_king = 'K' in hole_ranks
    n_overcards = sum(1 for v in hole_vals if v > top)

    # Позиционен анализ — работи и без villain_pos (heuristic за IP/OOP)
    pa = pos_adjust(hero_pos, villain_pos, bi) if hero_pos else dict(
        cbet=0, bluff=0, note="", ip=True
    )

    # ── Sizing по Upswing 8 Rules ──
    # Rule 3: Dry → малък бет (25-33%)
    # Rule 4: Wet → голям бет (55-80%)
    # Rule 7: Turn double barrel → 66%+ пот
    # Rule 8: 3-bet pot → 25-40% flop
    hero_ip = pa.get('ip', True)
    if street_name == 'river':
        # River: поляризиран range → 66-100% пот (Rule 6: overbet с nut advantage)
        sizing = "Sizing: 66-100% пот (поляризирай!)"
        default_bet_pct = RIVER_POLAR_PCT
    elif street_name == 'turn':
        # Rule 7: Turn double barrel → 66%+ пот
        if bi['is_dry']:
            sizing = "Sizing: 55-66% пот"
            default_bet_pct = TURN_DRY_PCT
        else:
            sizing = "Sizing: 66-75% пот"
            default_bet_pct = TURN_WET_PCT
    else:  # flop
        # Rule 3 & 4: dry=малко, wet=голямо
        if bi['is_dry']:
            sizing = "Sizing: 25-33% пот (dry: малко но често)"
            default_bet_pct = FLOP_DRY_PCT
        elif bi['is_paired']:
            # Upswing Paired Flops: малък sizing, висока честота
            sizing = "Sizing: 25-33% пот (paired: c-bet често)"
            default_bet_pct = FLOP_PAIRED_PCT
        elif bi['is_mono'] or (bi['is_connected'] and bi['is_two_tone']):
            sizing = "Sizing: 66-75% пот (wet: голям бет)"
            default_bet_pct = FLOP_WET_PCT
        elif bi['is_connected'] or bi['is_two_tone']:
            sizing = "Sizing: 50-66% пот"
            default_bet_pct = FLOP_MEDIUM_PCT
        elif bi['is_high']:
            # Nut advantage → малък бет, висока честота
            sizing = "Sizing: 33% пот (A/K high: c-bet често)"
            default_bet_pct = FLOP_HIGHDRY_PCT
        else:
            sizing = "Sizing: 33-50% пот"
            default_bet_pct = FLOP_OTHER_PCT

    pn = f"  [{pa['note']}]" if pa.get('note') else ""
    sn = f"  [{spr_note}]" if spr_note else ""
    mn = f"  [{mw_note}]" if mw_note else ""

    def _mw_adjust(action, color, hand_label):
        """При multiway смъкваме агресията за не-монстри:
        RAISE→CALL, BET→CHECK, освен при FLUSH/STRAIGHT/Сет/2pair."""
        if not is_multiway:
            return action, color
        strong_labels = ('FLUSH', 'STRAIGHT', 'Сет', 'Две двойки')
        if any(s in hand_label for s in strong_labels):
            return action, color  # монстрите запазват агресията
        a_upper = action.upper()
        if 'RAISE' in a_upper and 'CALL' not in a_upper:
            return action.replace('RAISE', 'CALL').replace('ALL-IN', 'CALL'), "#f0d060"
        if a_upper.startswith('BET') and 'CHECK' not in a_upper:
            return "CHECK (multiway)", "#f0d060"
        return action, color

    def R(a, c, h, r):
        a2, c2 = _mw_adjust(a, c, h)
        return dict(
            action=a2, color=c2, hand=h, reason=r + pn + sn + mn,
            sizing=sizing,
            hero_class=hero_class,
            hero_label=hero_label,
            threats=hero_threats,
        )

    # Draw outs (0 on river) — виж OUTS_* константи най-горе
    draw_outs = 0
    draw_tags = []
    if fd:                   draw_outs += OUTS_FD;      draw_tags.append(f"FD({OUTS_FD})")
    if oesd:                 draw_outs += OUTS_OESD;    draw_tags.append(f"OESD({OUTS_OESD})")
    if gutshot and not oesd: draw_outs += OUTS_GUTSHOT; draw_tags.append(f"gutshot({OUTS_GUTSHOT})")
    if bfd and not fd:       draw_outs += OUTS_BFD;     draw_tags.append(f"bfd({OUTS_BFD})")
    draw_str = " + ".join(draw_tags) if draw_tags else ""

    # Pot odds helpers — use streets_left
    def odds_ok(outs, bet_pct=default_bet_pct, streets=None):
        """Дали call е математически оправдан."""
        if streets is None:
            streets = streets_left
        if streets <= 0:
            return False  # river — no more cards
        eq = equity_from_outs(outs, streets)
        needed = pot_odds_needed(bet_pct)
        return eq >= needed

    def odds_str(outs, bet_pct=default_bet_pct, streets=None):
        if streets is None:
            streets = streets_left
        if streets <= 0:
            return "River — без карти за теглене"
        eq = equity_from_outs(outs, streets) * 100
        needed = pot_odds_needed(bet_pct) * 100
        return f"Equity ~{eq:.0f}% vs нужни {needed:.0f}%"

    # ═══════════════════════════════════════════════════════════════════════════
    #  MONSTERS: Quads, Full House, Flush, Straight, Сет, Trips, Две двойки
    # ═══════════════════════════════════════════════════════════════════════════

    # Pre-compute (used by quads/FH/trips checks)
    has_quads, quads_rank = made_quads(hole, board)
    has_fh, fh_trips, fh_pair = made_full_house(hole, board)
    has_trips, trips_rank, trips_kicker = made_trips(hole, board)

    # ── QUADS (Каре) — почти невъзможно да загубиш ──
    if has_quads:
        if facing_bet:
            return R("RAISE / SLOWPLAY", "#00e676",
                     f"QUADS {quads_rank}{quads_rank}{quads_rank}{quads_rank}",
                     "Каре — slowplay или raise. Малко ръце ще те платят.")
        return R("BET small / CHECK (trap)", "#00e676",
                 f"QUADS {quads_rank}{quads_rank}{quads_rank}{quads_rank}",
                 "Каре — малък бет за value или trap. Practically nuts.")

    # ── FULL HOUSE (Фул) ──
    if has_fh:
        label = f"Boat {fh_trips}{fh_trips}{fh_trips} full of {fh_pair}{fh_pair}"
        if facing_bet:
            return R("RAISE", "#00e676", label,
                     f"Фул {fh_trips}-те върху {fh_pair}-те — raise за value. "
                     f"Само по-добър boat или quads те бие.")
        if is_river:
            return R("BET 66-100%", "#00e676", label,
                     f"Фул на river — голям value bet (поляризиран range).")
        return R("BET", "#00e676", label,
                 f"Фул — бет за value. Натъпкай пота.")

    # ── Made Flush ──
    if has_made_flush:
        if facing_bet:
            return R("RAISE", "#00e676", "FLUSH!", "Flush — raise за стойност! Натъпкай пота.")
        return R("BET", "#00e676", "FLUSH!", "Flush — бет за стойност.")

    # ── Made Straight ──
    if has_made_straight:
        if facing_bet:
            if bi['is_mono']:
                return R("CALL", "#f0d060", "Straight (monotone!)", "Straight на monotone — call. Flush бие straight.")
            return R("RAISE", "#00e676", "STRAIGHT!", "Straight — raise за стойност!")
        return R("BET", "#00e676", "STRAIGHT!", "Straight — бет за стойност.")

    # ── Сет (pocket pair + matching board) ──
    if hole_ranks[0] == hole_ranks[1] and hole_ranks[0] in board_ranks:
        rk = hole_ranks[0]
        if bi['is_mono']:
            if facing_bet:
                return R("CALL (mono!)", "#f0d060", f"Сет {rk}{rk}", "Сет на monotone — call. Flush може да е готов.")
            return R("BET (protect)", "#60ff60", f"Сет {rk}{rk}", "Сет на monotone — бет за protection.")
        if facing_bet:
            return R("RAISE", "#00e676", f"Сет {rk}{rk}", "Сет — raise за стойност.")
        if is_river:
            return R("BET", "#00e676", f"Сет {rk}{rk}", "Сет на river — бет за стойност.")
        if bi['is_dry']:
            return R("CHECK (trap) / BET 33%", "#60ff60", f"Сет {rk}{rk}", "Сет dry борд — trap или малък бет.")
        return R("BET", "#60ff60", f"Сет {rk}{rk}", "Сет — бет за стойност + protection.")

    # ── TRIPS (paired board + 1 matching hole card) ──
    if has_trips:
        rk = trips_rank
        kk = trips_kicker
        kicker_strong = RV[kk] >= RV['T']
        # Trips kicker matters: weak kicker = vulnerable to higher trips
        # На paired board висок дял от ranges може да съдържа другия trip
        if bi['is_mono']:
            if facing_bet:
                return R("CALL", "#f0d060", f"Trips {rk}{rk}{rk} +{kk} kicker",
                         f"Trips на monotone — call. Flush бие trips.")
            return R("BET (protect)", "#60ff60", f"Trips {rk}{rk}{rk} +{kk} kicker",
                     f"Trips на monotone — бет за protection.")
        if facing_bet:
            if kicker_strong:
                return R("RAISE", "#00e676", f"Trips {rk}{rk}{rk} +{kk} kicker",
                         f"Trips с висок kicker ({kk}) — raise за value.")
            return R("CALL", "#f0d060", f"Trips {rk}{rk}{rk} +{kk} kicker",
                     f"Trips среден/слаб kicker — call (бой се от по-висок kicker/FH).")
        if is_river:
            if kicker_strong:
                return R("BET 50-66%", "#00e676", f"Trips {rk}{rk}{rk} +{kk} kicker",
                         f"Trips river — value bet с {kk} kicker.")
            return R("CHECK / BET 33%", "#60ff60", f"Trips {rk}{rk}{rk} +{kk} kicker",
                     f"Trips river слаб kicker — thin value или check.")
        return R("BET", "#60ff60", f"Trips {rk}{rk}{rk} +{kk} kicker",
                 f"Trips — бет за стойност. Vulnerable към FH на paired board.")

    # ── Две двойки ──
    if len(set(hr for hr in hole_ranks if hr in board_ranks)) == 2:
        if bi['is_mono']:
            if facing_bet:
                return R("CALL", "#f0d060", "Две двойки", "Две двойки mono — call.")
            return R("BET", "#60ff60", "Две двойки", "Две двойки — бет за protection.")
        if facing_bet:
            return R("RAISE", "#00e676", "Две двойки", "Две двойки — raise за стойност.")
        return R("BET", "#60ff60", "Две двойки", "Две двойки — бет за стойност.")

    # ═══════════════════════════════════════════════════════════════════════════
    #  OVERPAIR / UNDERPAIR
    # ═══════════════════════════════════════════════════════════════════════════
    if hole_ranks[0] == hole_ranks[1]:
        pv = RV[hole_ranks[0]]; nm = hole_ranks[0]*2
        if pv > top:
            if is_river:
                if facing_bet:
                    # High overpair (QQ+) strong vs most ranges; smaller overpairs (TT/JJ) bluff-catch
                    if pv >= RV['Q']:
                        return R("CALL / RAISE", "#f0d060", f"Overpair {nm}", f"{nm} river — call за value. Raise ако board dry и имаш blockers.")
                    return R("CALL", "#f0d060", f"Overpair {nm}", f"{nm} river — call (bluff-catch). MDF vs 50%={mdf_threshold(0.5)*100:.0f}%.")
                # River value sizing: overpair on dry → 50-66%, on wet → be cautious
                if bi.get('is_connected', False) or bi.get('is_mono', False):
                    return R("BET 33%", "#60ff60", f"Overpair {nm}", f"{nm} river wet — малък бет, полу-bluff-catch.")
                return R("BET 50-66%", "#60ff60", f"Overpair {nm}", f"{nm} river dry — value бет. Бий TP и по-малки overpairs.")
            # SPR-aware: низко SPR = лесен stack-off. Deep SPR = внимание.
            if bi['is_high'] or bi['is_mid']:
                if facing_bet:
                    if spr_name == 'commit':
                        return R("RAISE / ALL-IN", "#00e676", f"Overpair {nm}",
                                 f"{nm} висок борд commit SPR — raise за stack-off.")
                    if spr_name == 'deep':
                        return R("CALL", "#f0d060", f"Overpair {nm}",
                                 f"{nm} deep SPR — CALL (не raise). Набутваш само срещу по-силни ръце.")
                    return R("RAISE / CALL", "#00e676", f"Overpair {nm}", f"{nm} висок борд — raise за value или call.")
                return R("BET", "#60ff60", f"Overpair {nm}", f"{nm} — бет за стойност.")
            if hole_ranks[0] in ('A','K'):
                if facing_bet:
                    return R("RAISE", "#00e676", f"Overpair {nm}", f"{nm} — raise. Trap сработи.")
                return R("CHECK (trap)", "#f0d060", f"Overpair {nm}", f"{nm} нисък борд — trap. Check-raise при бет.")
            else:
                if facing_bet:
                    if spr_name == 'commit':
                        return R("RAISE", "#00e676", f"Overpair {nm}",
                                 f"{nm} commit SPR — raise за stack-off.")
                    return R("CALL", "#f0d060", f"Overpair {nm}", f"{nm} — call.")
                return R("BET", "#60ff60", f"Overpair {nm}", f"{nm} — бет за value + protection.")

        # Underpair
        gap = top - pv
        total_outs = (2 + draw_outs) if not is_river else 0
        if gap <= 2:
            if is_river:
                if facing_bet:
                    return R("CALL 33% / FOLD 50%+", "#ffb040", f"Underpair {nm}", f"{nm} river, близо — call малък бет.")
                return R("CHECK", "#f0d060", f"Underpair {nm}", f"{nm} river — чек, showdown value.")
            if facing_bet:
                if odds_ok(total_outs, 0.5):
                    return R("CALL", "#f0d060", f"Underpair {nm}", f"{nm} close + {total_outs} аута. {odds_str(total_outs, 0.5)}")
                return R("CALL 33% / FOLD 50%+", "#ffb040", f"Underpair {nm}", f"{nm} близо до борда. {odds_str(total_outs, 0.5)} — MDF vs 33%={mdf_threshold(0.33)*100:.0f}% (bluff-catch OK), vs 66%={mdf_threshold(0.66)*100:.0f}% (fold).")
            return R("CHECK", "#f0d060", f"Underpair {nm}", f"{nm} под борда — чек, showdown value.")
        else:
            if facing_bet:
                return R("FOLD", "#ff6060", f"Underpair {nm}", f"{nm} далеч под борда. {'River — fold.' if is_river else f'Само {total_outs} аута — fold.'}")
            return R("CHECK / FOLD", "#ff9060", f"Underpair {nm}", f"{nm} под борда — чек, fold при бет.")

    # ═══════════════════════════════════════════════════════════════════════════
    #  TOP PAIR / MIDDLE PAIR / BOTTOM PAIR
    # ═══════════════════════════════════════════════════════════════════════════
    top_r = [r for r in RANKS if RV[r]==top][0]
    # For mid/bot, use board ranks sorted desc — handle 3, 4, 5 cards
    mid_r = [r for r in RANKS if RV[r]==fs[1]][0] if len(fs) >= 2 else None
    bot_r = [r for r in RANKS if RV[r]==fs[-1]][0] if len(fs) >= 3 else None

    # ── Топ двойка (Upswing: OOP чекваш повече, IP bet повече) ──
    if top_r in hole_ranks:
        kicker = h2[0] if h1[0] == top_r else h1[0]
        kv = RV[kicker]
        has_bdfd = bfd and kv >= RV['T']  # backdoor FD = приоритет за c-bet OOP

        # ─── RIVER ───
        if is_river:
            if kv >= RV['T']:
                if facing_bet:
                    # River: TPTK call vs bet (blockers: имаме top card = villain по-рядко TP)
                    return R("CALL", "#f0d060", f"TP + {kicker}", f"TP добър кикер river — call. Блокираш TP комбинации на villain.")
                # River value bet thin (Upswing: бетвай слаби ръце за value)
                return R("BET 33-50% (thin)", "#60ff60", f"TP + {kicker}", f"TP + {kicker} river — thin value бет. Малък sizing за да те calling stations → weaker TP/middle pair. Голям бет = само 2pair+ ще call.")
            elif kv >= RV['7']:
                if facing_bet:
                    return R("CALL 33% / FOLD 50%+", "#ffb040", f"TP + {kicker}", f"TP среден кикер river — bluff-catch само vs малък бет. MDF 33%={mdf_threshold(0.33)*100:.0f}%, 66%={mdf_threshold(0.66)*100:.0f}%.")
                # Showdown value — чек (Upswing: ace-high type = чек river за showdown)
                return R("CHECK", "#f0d060", f"TP + {kicker}", f"TP среден кикер river — чек, showdown value.")
            else:
                if facing_bet:
                    return R("FOLD", "#ff6060", f"TP + {kicker}", f"TP слаб кикер river — fold. Доминиран.")
                return R("CHECK / FOLD", "#ffb040", f"TP + {kicker}", f"TP слаб({kicker}) river — чек. Без showdown value vs бет.")

        # ─── FLOP / TURN ───
        # TPTK (A-T кикер)
        if kv >= RV['T']:
            if facing_bet:
                if bi['is_mono']:
                    return R("CALL", "#f0d060", f"TP + {kicker}", f"TP+{kicker} mono — call. Fold 2nd barrel без FD.")
                # SPR-aware: commit zone → raise за stack-off; deep → pot control
                if spr_name == 'commit':
                    return R("RAISE (commit)", "#00e676", f"TP + {kicker}",
                             f"TP+{kicker} low SPR — raise за stack-off. SPR<{SPR_COMMIT} = committed.")
                if spr_name == 'deep':
                    return R("CALL small / FOLD big", "#ffb040", f"TP + {kicker}",
                             f"TP+{kicker} deep SPR — pot control. Не stack-offaй TP срещу голям натиск.")
                return R("CALL", "#f0d060", f"TP + {kicker}", f"TP добър кикер — call. Силна ръка за bluff-catch.")
            # Upswing OOP check rule: дори TPTK чекваш често OOP
            if not hero_ip and not bi['is_dry']:
                if has_bdfd:
                    return R("BET", "#60ff60", f"TP + {kicker}", f"TP+{kicker} OOP + backdoor — c-bet. Приоритет за бет с bdfd.")
                # Dynamic freq via cbet_frequency helper
                freq, sz, cnote = cbet_frequency(bi, 'strong', hero_ip, spr_name, num_opponents)
                if freq >= 0.5:
                    return R(f"BET {int(sz*100)}%", "#60ff60", f"TP + {kicker}",
                             f"TP+{kicker} OOP — bet ({int(freq*100)}% freq). {cnote}")
                return R(f"CHECK (mix {int((1-freq)*100)}%)", "#f0d060", f"TP + {kicker}",
                         f"TP+{kicker} OOP — чек по-често ({int((1-freq)*100)}%). {cnote}")
            # IP TPTK — freq-aware value bet
            freq, sz, cnote = cbet_frequency(bi, 'strong', True, spr_name, num_opponents)
            return R(f"BET {int(sz*100)}%", "#60ff60", f"TP + {kicker}",
                     f"Top pair + {kicker} — value bet ({int(freq*100)}% freq). {cnote}")

        # Среден кикер (7-9)
        elif kv >= RV['7']:
            if facing_bet:
                total = 5 + draw_outs
                if odds_ok(total, 0.5):
                    return R("CALL", "#f0d060", f"TP + {kicker}", f"TP среден кикер. {odds_str(total, 0.5)}")
                return R("CALL 33% / FOLD 50%+", "#ffb040", f"TP + {kicker}", f"TP среден кикер — call малък, fold голям. MDF vs 33%={mdf_threshold(0.33)*100:.0f}% (защити range).")
            if hero_ip:
                if bi['is_dry']:
                    return R("BET 33%", "#a0e060", f"TP + {kicker}", f"TP среден кикер dry IP — малък бет.")
                # Freq-aware mix for medium hand IP on non-dry
                freq, sz, cnote = cbet_frequency(bi, 'medium', True, spr_name, num_opponents)
                if freq >= 0.4:
                    return R(f"BET {int(sz*100)}%", "#a0e060", f"TP + {kicker}",
                             f"TP среден кикер IP — bet ({int(freq*100)}% freq). {cnote}")
                return R("CHECK (pot control)", "#f0d060", f"TP + {kicker}",
                         f"TP среден кикер IP — чек-бек. {cnote}")
            # OOP: чекваш повече (Upswing: marginal hands → check OOP)
            return R("CHECK", "#f0d060", f"TP + {kicker}", f"TP среден кикер OOP — чек. Пот контрол, избягвай check-raise.")

        # Слаб кикер (2-6) — Upswing: почти винаги чек, fold vs бет
        else:
            if facing_bet:
                if draw_outs >= 8:
                    return R("CALL", "#f0d060", f"TP слаб({kicker}) +дро", f"TP слаб но {draw_str}. Call с draw equity.")
                if draw_outs >= 4:
                    return R("CALL 33%", "#ffb040", f"TP слаб({kicker}) +дро", f"TP слаб + {draw_str}. Call само малък.")
                return R("FOLD", "#ff6060", f"TP + {kicker}", f"TP с {kicker} — fold! Доминиран. Reverse implied odds.")
            return R("CHECK / FOLD", "#ffb040", f"TP + {kicker}", f"TP слаб кикер ({kicker}) — чек. Fold при бет.")

    # ── Средна двойка ──
    if mid_r:
        for hr in hole_ranks:
            if hr == mid_r:
                other = h2[0] if h1[0] == hr else h1[0]
                ov = RV[other]
                if is_river:
                    if facing_bet:
                        return R("FOLD", "#ff6060", f"Mid pair ({hr})", f"Средна двойка river — fold.")
                    return R("CHECK / FOLD", "#ff9060", f"Mid pair ({hr})", "Средна двойка river — чек, fold при бет.")
                total_outs = 2 + draw_outs + (3 if ov > top else 0)
                if facing_bet:
                    if draw_outs >= 8 or (draw_outs >= 4 and ov > top):
                        return R("CALL", "#f0d060", f"Mid pair + {draw_str or 'overcard'}", f"Средна двойка + допълнителни аути ({total_outs}). {odds_str(total_outs, 0.5)}")
                    if ov > top:
                        return R("CALL 33%", "#ffb040", f"Mid pair ({hr}) + OC {other}", f"Средна двойка + overcard {other}. {total_outs} аута. Call само малък.")
                    return R("FOLD", "#ff6060", f"Mid pair ({hr})", f"Средна двойка без подобрение. {total_outs} аута — не достигат.")
                return R("CHECK", "#f0d060", f"Mid pair ({hr})", "Средна двойка — чек. Пот контрол.")

    # ── Долна двойка ──
    if bot_r:
        for hr in hole_ranks:
            if hr == bot_r:
                if is_river:
                    if facing_bet:
                        return R("FOLD", "#ff6060", f"Bot pair ({hr})", f"Долна двойка river — fold.")
                    return R("CHECK / FOLD", "#ff9060", f"Bot pair ({hr})", "Долна двойка river — чек, fold при бет.")
                total_outs = 2 + draw_outs
                if facing_bet:
                    if draw_outs >= 8:
                        return R("CALL", "#f0d060", f"Bot pair + {draw_str}", f"Долна двойка + draw. {odds_str(total_outs, 0.5)}")
                    return R("FOLD", "#ff6060", f"Bot pair ({hr})", f"Долна двойка, {total_outs} аута. Fold.")
                return R("CHECK / FOLD", "#ff9060", f"Bot pair ({hr})", "Долна двойка — чек, fold при бет.")

    # Also check if hole card pairs with ANY board card (not just top/mid/bot rank positions)
    for hr in hole_ranks:
        if hr in board_ranks and hr != top_r and (mid_r is None or hr != mid_r) and (bot_r is None or hr != bot_r):
            # Paired with a board card but not top/mid/bot — treat as bottom pair
            if is_river:
                if facing_bet:
                    return R("FOLD", "#ff6060", f"Pair ({hr})", f"Слаба двойка river — fold.")
                return R("CHECK / FOLD", "#ff9060", f"Pair ({hr})", "Слаба двойка river — чек, fold при бет.")
            total_outs = 2 + draw_outs
            if facing_bet:
                return R("FOLD", "#ff6060", f"Pair ({hr})", f"Слаба двойка, {total_outs} аута. Fold.")
            return R("CHECK / FOLD", "#ff9060", f"Pair ({hr})", "Слаба двойка — чек, fold при бет.")

    # ═══════════════════════════════════════════════════════════════════════════
    #  DRAWS (без made hand) — NOT on river
    #  Upswing: Fold equity = Risk / (Risk + Reward)
    #  Semi-bluff IP по-често, OOP по-selective (нужна backup equity)
    #  Implied odds: IP + nut draw + deep = добри; OOP + non-nut = лоши
    # ═══════════════════════════════════════════════════════════════════════════
    if not is_river:
        # Fold equity helper: min fold% needed for breakeven bluff
        def fold_eq_note(bet_pct=default_bet_pct):
            fe = bet_pct / (1 + bet_pct)
            return f"Fold equity нужна: {fe*100:.0f}%"

        # ── Комбо дро (FD + SD) ──
        if fd and (oesd or gutshot):
            eq = equity_from_outs(draw_outs, streets_left) * 100
            if facing_bet:
                # Combo draw = monster draw, always continue
                if hero_ip:
                    return R("RAISE", "#00e676", f"Комбо дро ({draw_str})", f"~{draw_outs} аута = {eq:.0f}% equity. Raise IP! По-силно от повечето made ръце.")
                # OOP: raise all-in или call (Upswing: OOP raises трябва по-polar)
                return R("RAISE / CALL", "#00e676", f"Комбо дро ({draw_str})", f"~{draw_outs} аута = {eq:.0f}% equity. OOP: raise (all-in?) или call. Monster draw.")
            # Not facing bet — semi-bluff
            if hero_ip:
                return R("BET", "#60ff60", f"Комбо дро ({draw_str})", f"~{draw_outs} аута = {eq:.0f}% equity — semi-bluff IP. {fold_eq_note()}")
            # OOP: bet combo draws (top priority for OOP semi-bluffs)
            return R("BET", "#60ff60", f"Комбо дро ({draw_str})", f"~{draw_outs} аута = {eq:.0f}% equity — OOP semi-bluff (приоритет: combo draw).")

        # ── Flush Draw ──
        if fd:
            eq = equity_from_outs(draw_outs, streets_left) * 100
            if nfd:
                # Nut FD — best implied odds (Upswing: nut draws IP = max implied odds)
                if facing_bet:
                    if hero_ip:
                        return R("CALL / RAISE", "#f0d060", f"Nut FD ({draw_str})", f"Nut FD IP {eq:.0f}% equity + max implied odds. Call (trap) или raise.")
                    return R("RAISE / CALL", "#f0d060", f"Nut FD ({draw_str})", f"Nut FD OOP {eq:.0f}% equity — raise (deny villain equity) или call.")
                if hero_ip:
                    return R("BET semi-bluff", "#a0e060", f"Nut FD ({draw_str})", f"Nut FD IP — semi-bluff. {eq:.0f}% equity + implied odds. {fold_eq_note()}")
                # OOP: nut FD е приоритет за c-bet (Upswing: backdoor → bet OOP)
                return R("BET semi-bluff", "#a0e060", f"Nut FD ({draw_str})", f"Nut FD OOP — semi-bluff (приоритет). {eq:.0f}% equity.")
            else:
                # Non-nut FD — implied odds по-лоши (Upswing: reverse implied odds при non-nut)
                if facing_bet:
                    if hero_ip and odds_ok(draw_outs, 0.66, streets_left):
                        return R("CALL", "#f0d060", f"FD ({draw_str})", f"FD IP {eq:.0f}% equity. {odds_str(draw_outs, 0.66)}. Implied odds IP компенсират.")
                    if odds_ok(draw_outs, 0.66, streets_left):
                        return R("CALL", "#f0d060", f"FD ({draw_str})", f"FD {eq:.0f}% equity. {odds_str(draw_outs, 0.66)}")
                    return R("CALL 50% / FOLD 75%+", "#ffb040", f"FD ({draw_str})", f"FD (не nut). {odds_str(draw_outs, 0.66)}. OOP: reverse implied odds!")
                if hero_ip:
                    return R("BET semi-bluff", "#a0e060", f"FD ({draw_str})", f"FD IP — semi-bluff. {eq:.0f}% equity. {fold_eq_note()}")
                # OOP non-nut FD: check повече (Upswing: OOP check non-nut draws)
                if bfd or n_overcards >= 1:
                    return R("BET semi-bluff", "#a0e060", f"FD ({draw_str})", f"FD OOP + backup equity — semi-bluff. {eq:.0f}%.")
                return R("CHECK", "#f0d060", f"FD ({draw_str})", f"FD OOP (не nut) — чек. Reverse implied odds при hit.")

        # ── OESD ──
        if oesd:
            eq = equity_from_outs(draw_outs, streets_left) * 100
            if facing_bet:
                if n_overcards >= 1:
                    total = draw_outs + n_overcards * 3
                    return R("CALL", "#f0d060", f"OESD + overcard ({total} аута)", f"{odds_str(total, 0.5)}")
                if hero_ip and odds_ok(draw_outs, 0.5, streets_left):
                    return R("CALL", "#f0d060", f"OESD ({draw_outs} аута)", f"OESD IP. {odds_str(draw_outs, 0.5)}. Implied odds IP.")
                if odds_ok(draw_outs, 0.5, streets_left):
                    return R("CALL", "#f0d060", f"OESD ({draw_outs} аута)", f"OESD. {odds_str(draw_outs, 0.5)}")
                return R("CALL 33% / FOLD 66%+", "#ffb040", "OESD", f"OESD 8 аута. {odds_str(draw_outs, 0.66)}")
            # Not facing bet — semi-bluff
            if hero_ip:
                return R("BET semi-bluff", "#a0e060", f"OESD ({draw_outs} аута)", f"OESD IP — semi-bluff. {eq:.0f}% equity. {fold_eq_note()}")
            # OOP: OESD semi-bluff само с backup equity
            if n_overcards >= 1 or bfd:
                return R("BET semi-bluff", "#a0e060", f"OESD ({draw_outs} аута)", f"OESD OOP + backup — semi-bluff. {eq:.0f}% equity.")
            return R("CHECK", "#f0d060", f"OESD ({draw_outs} аута)", f"OESD OOP — чек. Без backup equity. {eq:.0f}% equity.")

    # ═══════════════════════════════════════════════════════════════════════════
    #  ACE-HIGH / KING-HIGH
    #  Upswing Float: IP + 2 overcards + BDFD/GS = перфектен float
    #  Upswing River: A-high блокира villain's value range (AK/AQ)
    # ═══════════════════════════════════════════════════════════════════════════
    if has_ace and not any(hr in board_ranks for hr in hole_ranks):
        if is_river:
            if facing_bet:
                # Upswing: A-high bluff-catch на dry борд (blocker: имаме Ace)
                if bi['is_dry']:
                    return R("CALL 25-33% / FOLD 50%+", "#ffb040", "Ace-high (blocker)", f"A-high river dry — bluff-catch vs малък. Ace блокира AK/AQ на villain. MDF 25%={mdf_threshold(0.25)*100:.0f}%.")
                return R("FOLD", "#ff6060", "Ace-high", "A-high river без made hand — fold.")
            # Upswing River Bluff: A-high блокира villain's value (AK, AQ, AT)
            if bi['is_dry'] and pa.get('bluff', 0) >= 1:
                return R("BET bluff 50-66%", "#a0e060", "Ace-high (bluff)", "A-high river dry — bluff. Ace блокира villain's TP combos.")
            return R("CHECK / FOLD", "#ff9060", "Ace-high", "A-high river — чек, fold при бет.")
        total_outs, desc = count_outs('overcard', draw_outs, n_overcards, hole_vals)
        eq = equity_from_outs(total_outs, streets_left) * 100
        if gutshot and bfd:
            if facing_bet:
                # Upswing Float: A4s/A5s тип = key combo, float IP или check-raise OOP
                if hero_ip:
                    return R("CALL (float)", "#f0d060", f"Ace-high + GS + bfd", f"Float IP: {total_outs} аута ({eq:.0f}%). A-high + GS + bfd = перфектен float.")
                return R("RAISE semi-bluff", "#f0d060", f"Ace-high + GS + bfd", f"OOP check-raise: {total_outs} аута ({eq:.0f}%). Key bluff combo.")
            return R("BET semi-bluff", "#a0e060", f"Ace-high + GS + bfd", f"A-high + draws — semi-bluff. {total_outs} аута.")
        if gutshot:
            if facing_bet:
                # Upswing Float: IP + overcards + gutshot = добър float
                if hero_ip and n_overcards >= 2:
                    return R("CALL (float)", "#f0d060", f"Ace-high + GS (float IP)", f"Float IP: 2 OC + gutshot = {total_outs} аута. Position + implied odds.")
                if odds_ok(total_outs, 0.5, streets_left):
                    return R("CALL", "#f0d060", f"Ace-high + GS", f"A-high + gutshot. {total_outs} аута. {odds_str(total_outs, 0.5)}")
                return R("CALL 33% / FOLD", "#ffb040", f"Ace-high + GS", f"{total_outs} аута. {odds_str(total_outs, 0.5)}")
            return R("CHECK", "#f0d060", "Ace-high + GS", f"A-high + gutshot — чек. {total_outs} аута.")
        if bfd:
            if facing_bet:
                # Upswing Float: 2 OC + BDFD = перфектен float IP
                if hero_ip and n_overcards >= 2:
                    return R("CALL (float)", "#f0d060", "Ace-high + bfd (float IP)", f"Float IP: 2 OC + backdoor FD. Перфектен float. {total_outs} аута.")
                return R("CALL 33% / FOLD", "#ffb040", "Ace-high + bfd", f"A-high + bfd. {total_outs} аута. Само малък бет.")
            return R("CHECK", "#f0d060", "Ace-high + bfd", "A-high + bfd — чек.")
        # Чист ace-high — Upswing Float: IP + нисък борд + 2 overcards
        if facing_bet:
            if hero_ip and bi['is_low'] and n_overcards >= 2:
                return R("CALL (float)", "#ffb040", "Ace-high (float IP)", f"Float IP: 2 OC на нисък борд. {total_outs} аута = {eq:.0f}%. Plan: bet turn ако чекне.")
            if bi['is_low'] and total_outs >= 3:
                return R("CALL 25% / FOLD", "#ffb040", "Ace-high", f"A-high нисък борд. {total_outs} аута = {eq:.0f}%. Само мин. бет.")
            return R("FOLD", "#ff6060", "Ace-high", f"A-high без draws. {total_outs} аута — fold.")
        return R("CHECK", "#f0d060", "Ace-high", "A-high — чек.")

    if has_king and not any(hr in board_ranks for hr in hole_ranks):
        if is_river:
            if facing_bet:
                return R("FOLD", "#ff6060", "K-high", "K-high river — fold.")
            return R("CHECK / FOLD", "#ff9060", "K-high", "K-high river — чек, fold при бет.")
        total_outs, desc = count_outs('overcard', draw_outs, n_overcards, hole_vals)
        if bfd:
            if facing_bet:
                # Upswing Float: K-high + bfd = float IP
                if hero_ip and n_overcards >= 1:
                    return R("CALL (float)", "#f0d060", "K-high + bfd (float IP)", f"Float IP: K overcard + bfd. {total_outs} аута.")
                return R("RAISE semi-bluff", "#f0d060", "K-high + bfd", "K-high + bfd OOP — semi-bluff check-raise.")
            return R("BET semi-bluff", "#a0e060", "K-high + bfd", "K-high + bfd — semi-bluff.")
        if gutshot:
            if facing_bet:
                if hero_ip and n_overcards >= 1:
                    return R("CALL (float)", "#f0d060", "K-high + GS (float IP)", f"Float IP: K overcard + gutshot. {total_outs} аута.")
                if odds_ok(total_outs, 0.33, streets_left):
                    return R("CALL 33%", "#ffb040", "K-high + GS", f"{total_outs} аута. {odds_str(total_outs, 0.33)}")
                return R("FOLD", "#ff6060", "K-high + GS", f"K-high + GS. {total_outs} аута — недостатъчно.")
            return R("CHECK", "#f0d060", "K-high + GS", "K-high + gutshot — чек.")
        if facing_bet:
            return R("FOLD", "#ff6060", "K-high", "K-high без draws — fold.")
        return R("CHECK", "#f0d060", "K-high", "K-high — чек.")

    # ═══════════════════════════════════════════════════════════════════════════
    #  GUTSHOT / OVERCARDS / AIR
    #  Upswing River: поляризирай (strong value + bluffs), чекни medium
    #  Upswing Bluff: blocker-based (блокирай villain's folding range)
    #  Upswing Overbet: nut advantage борд → overbet river
    # ═══════════════════════════════════════════════════════════════════════════
    if is_river:
        # River without made hand — pure air
        if facing_bet:
            return R("FOLD", "#ff6060", "Air", "River без made hand — fold.")
        # Upswing River Bluff: нужни условия
        # 1) Dry борд (villain рядко има nuts)
        # 2) IP или nut advantage
        # 3) Blocker logic: не блокирай hands, които fold-ват
        if bi['is_dry'] and hero_ip and pa.get('bluff', 0) >= 1:
            # Upswing: overbet с nut advantage (A/K high dry борд)
            if bi['is_high'] and pa.get('cbet', 0) >= 1:
                return R("BET overbet bluff", "#a0e060", "Air (overbet bluff)", "River dry + A/K high IP — overbet bluff (125%+). Nut advantage!")
            return R("BET bluff 66%", "#a0e060", "Air (bluff IP)", "River dry IP — bluff. Fold при raise.")
        if bi['is_dry'] and pa.get('bluff', 0) >= 1:
            return R("BET bluff 50%", "#a0e060", "Air (bluff)", "River dry борд — малък bluff. Fold при raise.")
        return R("CHECK / FOLD", "#ff9060", "Air", "River без hand — чек, fold.")

    if gutshot:
        total_outs, desc = count_outs('gutshot_only', draw_outs, n_overcards, hole_vals)
        eq = equity_from_outs(total_outs, streets_left) * 100
        if n_overcards >= 1:
            if facing_bet:
                # Upswing Float: GS + overcard IP = добър float
                if hero_ip and n_overcards >= 2:
                    return R("CALL (float)", "#f0d060", f"GS + 2 OC (float IP)", f"Float IP: GS + 2 OC = {total_outs} аута. Position + implied odds.")
                if odds_ok(total_outs, 0.5, streets_left):
                    return R("CALL", "#f0d060", f"GS + overcard ({total_outs} аута)", f"{odds_str(total_outs, 0.5)}")
                return R("CALL 33% / FOLD", "#ffb040", f"GS + overcard", f"{total_outs} аута = {eq:.0f}%. Call малък.")
            return R("CHECK", "#f0d060", f"GS + overcard", f"Gutshot + overcard ({total_outs} аута) — чек.")
        if facing_bet:
            if odds_ok(draw_outs, 0.33, streets_left):
                return R("CALL 33%", "#ffb040", f"Gutshot ({draw_outs} аута)", f"{odds_str(draw_outs, 0.33)}")
            return R("FOLD", "#ff6060", "Gutshot", f"Gutshot. Само {draw_outs} аута = {eq:.0f}%. Fold.")
        return R("CHECK", "#f0d060", f"Gutshot ({draw_outs} аута)", "Gutshot — чек.")

    if n_overcards >= 2:
        total_outs, desc = count_outs('air', draw_outs, n_overcards, hole_vals)
        eq = equity_from_outs(total_outs, streets_left) * 100
        if bfd:
            if facing_bet:
                # Upswing Float: 2 OC + BDFD IP = перфектен float
                if hero_ip:
                    return R("CALL (float)", "#f0d060", f"2 OC + bfd (float IP)", f"Float IP: 2 OC + bfd = {total_outs} аута ({eq:.0f}%). Перфектен float.")
                return R("CALL 33% / FOLD", "#ffb040", f"2 OC + bfd ({total_outs} аута)", f"OOP: {total_outs} аута = {eq:.0f}%. Само малък бет.")
            if hero_ip:
                return R("BET semi-bluff", "#a0e060", f"2 OC + bfd", f"IP: Overcards + bfd — semi-bluff. {total_outs} аута.")
            return R("CHECK", "#f0d060", f"2 OC + bfd", f"OOP: Overcards + bfd — чек. {total_outs} аута. Без позиция не bluff-ваме.")
        if facing_bet:
            # Upswing Float: чист 2 OC = маргинален float само IP + dry
            if hero_ip and bi['is_dry']:
                return R("CALL (float маргинален)", "#ffb040", "2 OC (float IP)", f"Float IP dry: 2 OC = {total_outs} аута ({eq:.0f}%). Bet turn ако чекне.")
            return R("FOLD", "#ff6060", "2 overcards", f"Overcards. {total_outs} аута = {eq:.0f}%. Дори при hit може доминация. Fold.")
        if hero_ip and pa.get('bluff', 0) >= 1 and bi['is_dry']:
            return R("BET bluff", "#a0e060", "2 OC (bluff IP)", "IP dry борд — bluff. Fold при raise.")
        return R("CHECK / FOLD", "#ff9060", "2 overcards", f"Overcards без draw — чек, fold при бет.")

    if n_overcards == 1:
        total_outs, desc = count_outs('air', draw_outs, 1, hole_vals)
        if facing_bet:
            return R("FOLD", "#ff6060", "1 overcard", f"Само 1 overcard, {total_outs} аута. Fold.")
        return R("CHECK / FOLD", "#ff9060", "1 overcard", "1 overcard — чек, fold.")

    # ── Пълен въздух ──
    if facing_bet:
        return R("FOLD", "#ff6060", "Air", "0 аута. Fold.")
    if hero_ip and bi['is_dry'] and pa.get('bluff', 0) >= 1:
        return R("BET bluff", "#a0e060", "Air (bluff IP)", "IP dry борд — рядък bluff. Fold при raise.")
    return R("CHECK / FOLD", "#ff9060", "Air", "Нищо — чек, fold.")


# ─── GUI ──────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    BG = "#1b3a2a"; BG2 = "#0f2419"; GOLD = "#f0d060"
    CARD_BG = "#faf8f0"; SEL_HOLE = "#ffe040"; SEL_FLOP = "#60d0ff"
    POS_BG = "#2a5a3a"; POS_SEL = "#f0d060"; POS_FG_SEL = "#1b3a2a"

    def __init__(self):
        super().__init__()
        self.title("♠ Poker Decision Tool")
        self.configure(bg=self.BG)
        self.resizable(False, False)
        self.hole = []; self.flop = []
        self.card_btns = {}
        self.facing_bet = tk.BooleanVar(value=False)
        self.facing_raise = tk.BooleanVar(value=False)
        self.hero_pos = tk.StringVar(value="")
        self.villain_pos = tk.StringVar(value="")
        self.hero_btns = {}; self.villain_btns = {}
        self._build()
        self._update_all()

    def _build(self):
        # ── Хедър ──
        hdr = tk.Frame(self, bg=self.BG2, pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text="♠ Poker Decision Tool ♠", bg=self.BG2, fg=self.GOLD,
                 font=("Segoe UI", 14, "bold")).pack()

        # ── Позиции (опционално) ──
        pos_frame = tk.Frame(self, bg=self.BG, pady=2)
        pos_frame.pack(fill="x", padx=16)
        tk.Label(pos_frame, text="Позиции (опционално):", bg=self.BG, fg="#77aa77",
                 font=("Segoe UI", 8)).pack(anchor="w")

        row1 = tk.Frame(pos_frame, bg=self.BG)
        row1.pack(fill="x", pady=1)
        tk.Label(row1, text="Ти:", bg=self.BG, fg="#ccc", font=("Segoe UI", 9), width=10, anchor="e").pack(side="left")
        for p in ['UTG','MP','CO','BTN','SB','BB']:
            btn = tk.Button(row1, text=p, width=4, font=("Segoe UI", 8, "bold"),
                            bg=self.POS_BG, fg="white", relief="flat", cursor="hand2",
                            command=lambda x=p: self._set_hero(x))
            btn.pack(side="left", padx=1)
            self.hero_btns[p] = btn

        row2 = tk.Frame(pos_frame, bg=self.BG)
        row2.pack(fill="x", pady=1)
        tk.Label(row2, text="Опонент:", bg=self.BG, fg="#ccc", font=("Segoe UI", 9), width=10, anchor="e").pack(side="left")
        for p in ['UTG','MP','CO','BTN','SB','BB']:
            btn = tk.Button(row2, text=p, width=4, font=("Segoe UI", 8, "bold"),
                            bg=self.POS_BG, fg="white", relief="flat", cursor="hand2",
                            command=lambda x=p: self._set_villain(x))
            btn.pack(side="left", padx=1)
            self.villain_btns[p] = btn

        # ── Статус ──
        self.status_var = tk.StringVar()
        tk.Label(self, textvariable=self.status_var, bg=self.BG, fg="white",
                 font=("Segoe UI", 10, "bold"), pady=2).pack()

        # ── Избрани карти ──
        sel = tk.Frame(self, bg=self.BG, pady=2)
        sel.pack()
        tk.Label(sel, text="Ръка:", bg=self.BG, fg="#aaa", font=("Segoe UI", 9)).grid(row=0, column=0, padx=2)
        self.hole_labels = []
        for i in range(2):
            lbl = tk.Label(sel, text=" ? ", bg="#333", fg="white",
                           font=("Segoe UI", 13, "bold"), width=4, relief="groove")
            lbl.grid(row=0, column=i+1, padx=2)
            self.hole_labels.append(lbl)
        tk.Label(sel, text="  Флоп:", bg=self.BG, fg="#aaa", font=("Segoe UI", 9)).grid(row=0, column=3, padx=2)
        self.flop_labels = []
        for i in range(3):
            lbl = tk.Label(sel, text=" ? ", bg="#333", fg="white",
                           font=("Segoe UI", 13, "bold"), width=4, relief="groove")
            lbl.grid(row=0, column=i+4, padx=2)
            self.flop_labels.append(lbl)

        # ── Карти grid ──
        cf = tk.Frame(self, bg=self.BG, pady=4)
        cf.pack()
        for si, suit in enumerate(SUITS):
            for ri, rank in enumerate(RANKS):
                card = (rank, suit)
                txt = f"{rank}{SYM[suit]}"
                btn = tk.Button(cf, text=txt, width=4, height=1,
                                font=("Segoe UI", 10, "bold"),
                                bg=self.CARD_BG, fg=SCLR[suit],
                                relief="raised", bd=1, cursor="hand2",
                                command=lambda c=card: self._click(c))
                btn.grid(row=si, column=ri, padx=1, pady=1)
                self.card_btns[card] = btn

        # ── Контроли ──
        ctrl = tk.Frame(self, bg=self.BG, pady=2)
        ctrl.pack()
        tk.Checkbutton(ctrl, text="Facing Raise (preflop)",
                       variable=self.facing_raise, bg=self.BG, fg="#aaddff",
                       selectcolor="#2d6e44", font=("Segoe UI", 9),
                       activebackground=self.BG, command=self._update_all).pack(side="left", padx=6)
        tk.Checkbutton(ctrl, text="Facing Bet (postflop)",
                       variable=self.facing_bet, bg=self.BG, fg=self.GOLD,
                       selectcolor="#2d6e44", font=("Segoe UI", 9),
                       activebackground=self.BG, command=self._update_all).pack(side="left", padx=6)
        tk.Button(ctrl, text="ИЗЧИСТИ", command=self._reset,
                  bg="#884040", fg="white", font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=10, cursor="hand2").pack(side="left", padx=6)

        # ── Борд текстура ──
        self.texture_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.texture_var, bg=self.BG, fg="#88ccaa",
                 font=("Segoe UI", 9), pady=1).pack()

        # ── PREFLOP резултат ──
        pf = tk.Frame(self, bg="#1a2e20", bd=0)
        pf.pack(fill="x", padx=14, pady=2)
        tk.Label(pf, text="PREFLOP", bg="#1a2e20", fg="#88aaff", font=("Segoe UI", 8, "bold"),
                 anchor="w", padx=8).pack(anchor="w")
        self.pf_action_var = tk.StringVar(value="")
        self.pf_reason_var = tk.StringVar(value="")
        self.pf_action_lbl = tk.Label(pf, textvariable=self.pf_action_var, bg="#1a2e20",
                                      fg=self.GOLD, font=("Segoe UI", 16, "bold"),
                                      wraplength=580, pady=4)
        self.pf_action_lbl.pack()
        tk.Label(pf, textvariable=self.pf_reason_var, bg="#1a2e20", fg="#ccc",
                 font=("Segoe UI", 9), wraplength=580, pady=2, justify="center").pack()

        # ── POSTFLOP резултат ──
        res = tk.Frame(self, bg=self.BG2, bd=0)
        res.pack(fill="x", padx=14, pady=2)
        tk.Label(res, text="POSTFLOP", bg=self.BG2, fg="#ffaa44", font=("Segoe UI", 8, "bold"),
                 anchor="w", padx=8).pack(anchor="w")
        self.action_var = tk.StringVar(value="")
        self.hand_var = tk.StringVar(value="")
        self.reason_var = tk.StringVar(value="")
        self.sizing_var = tk.StringVar(value="")

        self.action_lbl = tk.Label(res, textvariable=self.action_var, bg=self.BG2,
                                   fg=self.GOLD, font=("Segoe UI", 16, "bold"),
                                   wraplength=580, pady=4)
        self.action_lbl.pack()
        tk.Label(res, textvariable=self.hand_var, bg=self.BG2, fg="#aaddaa",
                 font=("Segoe UI", 10), pady=1).pack()
        tk.Label(res, textvariable=self.reason_var, bg=self.BG2, fg="#ddd",
                 font=("Segoe UI", 9), wraplength=580, pady=2, justify="center").pack()
        tk.Label(res, textvariable=self.sizing_var, bg=self.BG2, fg="#ffcc66",
                 font=("Segoe UI", 9, "bold"), pady=2).pack()

    # ── Position toggles ──
    def _set_hero(self, p):
        self.hero_pos.set("" if self.hero_pos.get() == p else p)
        cur = self.hero_pos.get()
        for k, b in self.hero_btns.items():
            b.config(bg=self.POS_SEL if k == cur else self.POS_BG,
                     fg=self.POS_FG_SEL if k == cur else "white")
        self._update_all()

    def _set_villain(self, p):
        self.villain_pos.set("" if self.villain_pos.get() == p else p)
        cur = self.villain_pos.get()
        for k, b in self.villain_btns.items():
            b.config(bg=self.POS_SEL if k == cur else self.POS_BG,
                     fg=self.POS_FG_SEL if k == cur else "white")
        self._update_all()

    # ── Card click ──
    def _click(self, card):
        if card in self.hole:
            self.hole.remove(card)
            self.card_btns[card].config(bg=self.CARD_BG, relief="raised")
        elif card in self.flop:
            self.flop.remove(card)
            self.card_btns[card].config(bg=self.CARD_BG, relief="raised")
        else:
            if len(self.hole) < 2:
                self.hole.append(card)
                self.card_btns[card].config(bg=self.SEL_HOLE, relief="sunken")
            elif len(self.flop) < 3:
                self.flop.append(card)
                self.card_btns[card].config(bg=self.SEL_FLOP, relief="sunken")
        self._update_all()

    # ── Update everything ──
    def _update_all(self):
        # Status
        if len(self.hole) < 2:
            n = 2 - len(self.hole)
            self.status_var.set(f"Избери {n} карт{'а' if n==1 else 'и'} за РЪКАТА")
        elif len(self.flop) < 3:
            n = 3 - len(self.flop)
            self.status_var.set(f"Избери {n} карт{'а' if n==1 else 'и'} за ФЛОПА (или виж preflop съвета)")
        else:
            self.status_var.set("Готово!")

        # Selected card labels
        for i, lbl in enumerate(self.hole_labels):
            if i < len(self.hole):
                r, s = self.hole[i]
                lbl.config(text=f"{r}{SYM[s]}", fg=SCLR[s], bg=self.SEL_HOLE)
            else:
                lbl.config(text=" ? ", fg="white", bg="#333")
        for i, lbl in enumerate(self.flop_labels):
            if i < len(self.flop):
                r, s = self.flop[i]
                lbl.config(text=f"{r}{SYM[s]}", fg=SCLR[s], bg=self.SEL_FLOP)
            else:
                lbl.config(text=" ? ", fg="white", bg="#333")

        # Board texture
        if len(self.flop) == 3:
            self.texture_var.set("Борд: " + " · ".join(texture_tags(board_info(self.flop))))
        else:
            self.texture_var.set("")

        # ── PREFLOP analysis ──
        if len(self.hole) == 2:
            hp = self.hero_pos.get() or None
            vp = self.villain_pos.get() or None
            fr = self.facing_raise.get()
            pf = preflop_analyze(self.hole, hp, fr, vp)
            self.pf_action_var.set(pf["action"])
            self.pf_reason_var.set(pf["reason"])
            self.pf_action_lbl.config(fg=pf["color"])
        else:
            self.pf_action_var.set("")
            self.pf_reason_var.set("Избери 2 карти за preflop съвет")
            self.pf_action_lbl.config(fg="#888")

        # ── POSTFLOP analysis ──
        if len(self.hole) == 2 and len(self.flop) == 3:
            hp = self.hero_pos.get() or None
            vp = self.villain_pos.get() or None
            r = postflop_analyze(self.hole, self.flop, self.facing_bet.get(), hp, vp)
            self.action_var.set(r["action"])
            self.hand_var.set(f"Ръка: {r['hand']}")
            self.reason_var.set(r["reason"])
            self.sizing_var.set(r.get("sizing", ""))
            self.action_lbl.config(fg=r["color"])
        else:
            self.action_var.set("")
            self.hand_var.set("")
            self.reason_var.set("Добави 3 карти за флоп" if len(self.hole) == 2 else "")
            self.sizing_var.set("")
            self.action_lbl.config(fg="#888")

    def _reset(self):
        self.hole.clear(); self.flop.clear()
        self.facing_bet.set(False); self.facing_raise.set(False)
        self.hero_pos.set(""); self.villain_pos.set("")
        for b in self.card_btns.values():
            b.config(bg=self.CARD_BG, relief="raised")
        for b in self.hero_btns.values():
            b.config(bg=self.POS_BG, fg="white")
        for b in self.villain_btns.values():
            b.config(bg=self.POS_BG, fg="white")
        self._update_all()


if __name__ == "__main__":
    app = App()
    app.mainloop()
