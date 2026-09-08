# -*- coding: utf-8 -*-
"""Правки v75: мерч, дохляки со скидкой, приз, «есть ещё 1 тварь»."""
from backend.game import GameState, MAX_LIFE, START_LIFE, LOSHARA_MAX_LIFE


def _game(n=2, seed=7):
    g = GameState([f"P{i}" for i in range(n)], seed=seed)
    g.turn_idx = 0
    return g


# --- 1. Эпичный мерч боевых магов: -2 на легенды -------------------------
def test_epicmerch_discounts_legends():
    g = _game()
    p = g.players[0]
    lid = g.legend_market[0]
    full = g.cards[lid].cost
    p.hand.append("treas_epicmerch")
    g.play_card(p, "treas_epicmerch")
    assert p.legend_discount_turn == 2
    p.power_available = 99
    assert g.buy_card(p, lid) == {"ok": True}
    assert 99 - p.power_available == max(0, full - 2)


def test_epicmerch_stacks_and_resets_next_turn():
    g = _game()
    p = g.players[0]
    p.hand += ["treas_epicmerch", "treas_epicmerch"]
    g.play_card(p, "treas_epicmerch")
    g.play_card(p, "treas_epicmerch")
    assert p.legend_discount_turn == 4
    g.end_turn(p)
    g.turn_idx = 0
    g.start_turn()
    assert p.legend_discount_turn == 0


# --- 2. Дохляки и свойство «Скидка на сокровища» -------------------------
def test_treasure_discount_does_not_apply_to_dohlyak():
    g = _game()
    p = g.players[0]
    p.property_id = "svo_1"
    g.market.append("sdk_1")
    p.power_available = 0
    assert "error" in g.buy_card(p, "sdk_1")       # бесплатно нельзя
    p.power_available = 1
    assert g.buy_card(p, "sdk_1") == {"ok": True}
    assert p.power_available == 0


def test_treasure_discount_still_works_on_treasures():
    g = _game()
    p = g.players[0]
    p.property_id = "svo_1"
    g.market.append("treas_epicmerch")
    p.power_available = g.cards["treas_epicmerch"].cost - 1
    assert g.buy_card(p, "treas_epicmerch") == {"ok": True}


# --- 3. Приз переходит только от его владельца ---------------------------
def test_prize_only_from_its_holder():
    g = _game(3)
    holder, killer, victim = g.players
    holder.controls_prize = True
    g.prize_holder = holder.id
    g._handle_death(victim, killer)
    assert holder.controls_prize and g.prize_holder == holder.id
    assert not killer.controls_prize


def test_prize_moves_when_holder_killed():
    g = _game(3)
    holder, killer, _ = g.players
    holder.controls_prize = True
    g.prize_holder = holder.id
    g._handle_death(holder, killer)
    assert killer.controls_prize and g.prize_holder == killer.id
    assert not holder.controls_prize


def test_no_prize_on_suicide():
    g = _game(2)
    holder, _ = g.players
    holder.controls_prize = True
    g.prize_holder = holder.id
    g._handle_death(holder, holder)
    assert holder.controls_prize


# --- 4. «Если есть ещё 1 тварь» -----------------------------------------
def test_extra_beast_counts_hand_and_duplicates():
    g = _game()
    p = g.players[0]
    # две одинаковые твари: exclude_id снимает ровно один экземпляр,
    # а не все карты с этим id — вторая копия обязана засчитаться
    p.zone_in_play += ["beast_ork", "beast_ork"]
    assert g.has_extra_of_type(p, "Тварь", "beast_ork")
    # одна-единственная копия (она же разыгранная) — это НЕ «ещё одна тварь»
    p.zone_in_play = ["beast_ork"]
    assert not g.has_extra_of_type(p, "Тварь", "beast_ork")
    # только на руке
    p2 = g.players[1]
    p2.hand.append("beast_peyot")
    assert g.has_extra_of_type(p2, "Тварь", "beast_ork")


def test_ork_gets_bonus_with_beast_in_hand():
    g = _game()
    p = g.players[0]
    p.hand += ["beast_ork", "beast_peyot"]
    g.play_card(p, "beast_ork")
    assert p.power_available == g.cards["beast_ork"].power + 2


def test_peyot_chip_with_other_beast_in_hand():
    g = _game()
    p = g.players[0]
    p.hand += ["beast_peyot", "beast_ork"]
    before = p.chipsines
    g.play_card(p, "beast_peyot")
    assert p.chipsines == before + 1


def test_no_bonus_when_beast_is_alone():
    g = _game()
    p = g.players[0]
    p.hand = ["beast_ork"]
    g.play_card(p, "beast_ork")
    assert p.power_available == g.cards["beast_ork"].power


# --- 5. Свойство «Главный приз»: воскрешение на 25 -----------------------
def test_svo6_revives_with_25():
    g = _game()
    p, killer = g.players
    p.property_id = "svo_6"
    g.apply_property_setup(p)
    assert p.life == MAX_LIFE
    p.life = 0
    g.undead_token_stack = []
    g._handle_death(p, killer)
    assert p.life == MAX_LIFE


def test_svo6_loshara_revives_with_15():
    g = _game()
    p, killer = g.players
    p.property_id = "svo_6"
    g.apply_property_setup(p)
    g.set_loshara(p, True)
    g.undead_token_stack = []
    g._handle_death(p, killer)
    assert p.life == LOSHARA_MAX_LIFE


def test_ordinary_player_revives_with_20():
    g = _game()
    p, killer = g.players
    g.undead_token_stack = []
    g._handle_death(p, killer)
    assert p.life == START_LIFE


# --- 6. Приз не даёт ПО --------------------------------------------------
def test_prize_no_vp():
    g = _game()
    holder, other = g.players
    holder.controls_prize = True
    g._finish_game()
    assert g.final_scores[holder.id]["vp"] == g.final_scores[other.id]["vp"]
