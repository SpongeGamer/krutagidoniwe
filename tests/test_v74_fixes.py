"""Тесты правок v74: Трондец, подсчёт фамильяров, переименование жетона."""
import json
import os

import pytest

from backend.game import GameState

ROOT = os.path.join(os.path.dirname(__file__), "..")


def make_game(names=("A", "B"), seed=4):
    return GameState(list(names), seed=seed)


# --------------------------------------------------------------------------
# Трондец
# --------------------------------------------------------------------------

def test_throne_attacks_only_once_per_turn():
    """«Трондец» — это атака, а атака одна за ход. Раньше жалось бесконечно."""
    game = make_game()
    me, foe = game.players
    me.zone_in_play = ["leg_throne", "place_dirty"]

    first = game.activate_permanent(me, "leg_throne", target_id=foe.id)
    assert first.get("ok"), first
    game.resolve_decision(me, next(o["id"] for o in game.pending_decision["options"]))
    if game.pending_decision:      # окно защиты у цели
        game.resolve_decision(foe, game.pending_decision["options"][0]["id"])

    second = game.activate_permanent(me, "leg_throne", target_id=foe.id)
    assert "error" in second, "второй раз за ход бить нельзя"
    assert "уже атаковал" in second["error"]


def test_throne_available_again_next_turn():
    """На следующем своём ходу Трондец снова готов."""
    game = make_game()
    me, foe = game.players
    me.zone_in_play = ["leg_throne", "place_dirty"]

    game.activate_permanent(me, "leg_throne", target_id=foe.id)
    game.resolve_decision(me, next(o["id"] for o in game.pending_decision["options"]))
    while game.pending_decision:
        p = game.get_player(game.pending_decision["player_id"])
        game.resolve_decision(p, game.pending_decision["options"][0]["id"])

    assert "leg_throne" in me.used_activations
    game.turn_idx = 0
    game.start_turn()
    assert me.used_activations == [], "новый ход обнуляет использованные активации"
    assert game.activate_permanent(me, "leg_throne", target_id=foe.id).get("ok")


def test_throne_lets_player_choose_damage_card():
    """Урон выбирает ИГРОК, а не движок по самой дорогой постоянке."""
    game = make_game()
    me, foe = game.players
    me.zone_in_play = ["leg_throne", "place_dirty"]     # 5
    me.hand = ["leg_captain"]                           # 9

    game.activate_permanent(me, "leg_throne", target_id=foe.id)
    dec = game.pending_decision
    assert dec, "должно открыться окно выбора"
    labels = [o["label"] for o in dec["options"]]
    assert any("Капитан" in x for x in labels), "карта с руки обязана быть в списке"
    assert any("Грязная палка" in x for x in labels), "постоянка со стола тоже"

    hp = foe.life
    pick = next(o["id"] for o in dec["options"] if "Капитан" in o["label"])
    game.resolve_decision(me, pick)
    while game.pending_decision:
        p = game.get_player(game.pending_decision["player_id"])
        game.resolve_decision(p, game.pending_decision["options"][0]["id"])
    assert hp - foe.life == 9, "урон равен стоимости ВЫБРАННОЙ карты"


def test_throne_counts_hand_and_played_cards():
    """«Под контролем» = стол + сыграно в этот ход + рука."""
    game = make_game()
    me, foe = game.players
    me.zone_in_play = ["leg_throne"]
    me.in_play_this_turn = ["start_znak"]
    me.hand = ["leg_captain"]

    game.activate_permanent(me, "leg_throne", target_id=foe.id)
    zones = {o["detail"].split(" · ")[0] for o in game.pending_decision["options"]}
    assert "рука" in zones
    assert "сыграна" in zones


def test_throne_without_other_cards_does_nothing():
    game = make_game()
    me, foe = game.players
    me.zone_in_play = ["leg_throne"]
    me.hand = []
    me.in_play_this_turn = []

    game.activate_permanent(me, "leg_throne", target_id=foe.id)
    assert game.pending_decision is None, "выбирать нечего — окна быть не должно"
    assert foe.life == 20


# --------------------------------------------------------------------------
# Фамильяры в подсчёте очков
# --------------------------------------------------------------------------

def test_familiar_vp_counted_once():
    """Купленный фамильяр лежит в колоде — его ПО нельзя считать дважды."""
    game = make_game(seed=1)
    me = game.players[0]
    me.familiar_card_ids = ["fam_benz"]
    me.familiar_card_id = "fam_benz"
    me.power_available = 10
    game.buy_familiar(me, "fam_benz")

    game._finish_game()
    score = game.final_scores[me.id]
    fam_vp = game.cards["fam_benz"].vp
    assert score["vp"] == fam_vp, f"ожидали {fam_vp} ПО, а не двойной счёт"


def test_all_three_familiars_counted():
    """Свойство «Фамильяры»: все купленные фамильяры дают очки."""
    game = make_game(seed=2)
    me = game.players[0]
    fams = ["fam_benz", "fam_conduct", "fam_jester"]
    me.familiar_card_ids = fams
    me.familiar_card_id = fams[0]
    me.property_id = "svo_2"
    for fid in fams:
        me.power_available = 10
        assert game.buy_familiar(me, fid).get("ok"), fid

    game._finish_game()
    score = game.final_scores[me.id]
    expected = sum(game.cards[f].vp for f in fams)
    assert score["vp"] == expected, f"ожидали {expected} ПО за трёх фамильяров"

    notes = [s for s in score["steps"] if s.get("kind") == "note"]
    assert len(notes) == 3, "в разбивке должны быть видны все три фамильяра"
    for s in notes:
        assert s["delta"] == 0, "пояснение не должно менять сумму"


def test_unbought_familiar_gives_nothing():
    game = make_game(seed=3)
    me = game.players[0]
    me.familiar_card_ids = ["fam_benz"]
    me.familiar_card_id = "fam_benz"
    game._finish_game()
    assert game.final_scores[me.id]["vp"] == 0


# --------------------------------------------------------------------------
# Жетон переименован
# --------------------------------------------------------------------------

def test_token_renamed_to_chipsov():
    with open(os.path.join(ROOT, "zhdk.json"), encoding="utf-8") as f:
        tokens = json.load(f)
    names = [t["name"] for t in tokens]
    assert "Раздача чипсов на спавне" in names
    assert "Раздача чипсинов на спавне" not in names


def test_renamed_token_visible_in_state():
    """Игрок должен видеть новое имя жетона в своём планшете."""
    game = make_game()
    me = game.players[0]
    tid = next(t for t, v in game.zhdk.items()
               if v.get("name") == "Раздача чипсов на спавне")
    me.death_tokens.append(tid)
    out = game.to_public_dict(me.id)["players"][0]["death_token_cards"]
    assert any(t["name"] == "Раздача чипсов на спавне" for t in out)


# --------------------------------------------------------------------------
# Оплата легенд чипсинами при достатке мощи
# --------------------------------------------------------------------------

def test_legend_can_be_paid_by_chips_even_with_enough_power():
    """Мощь можно сберечь на вторую покупку, заплатив чипсинами."""
    game = make_game(seed=9)
    me = game.players[0]
    legend_id = game.legend_market[0]
    cost = game.cards[legend_id].cost
    me.power_available = cost + 3
    me.chipsines = cost

    result = game.buy_card(me, legend_id, use_chipsines=cost)
    assert result.get("ok"), result
    assert me.power_available == cost + 3, "мощь должна остаться нетронутой"
    assert me.chipsines == 0
