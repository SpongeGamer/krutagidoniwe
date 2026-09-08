# -*- coding: utf-8 -*-
"""Панель ведущего: команды работают, а без токена — не пускает."""
import pytest

from backend import gm
from backend.game import GameState, MAX_LIFE


@pytest.fixture
def game():
    g = GameState(["A", "B", "C"], seed=3)
    g.turn_idx = 0
    return g


# --- защита --------------------------------------------------------------
def test_token_required():
    assert not gm.check_token("")
    assert not gm.check_token(None)
    assert not gm.check_token("wrong-token")
    assert gm.check_token(gm.GM_TOKEN)
    assert gm.check_token(f"  {gm.GM_TOKEN}  ")   # пробелы при копипасте


def test_token_is_not_trivial():
    assert len(gm.GM_TOKEN) >= 8


def test_unknown_command(game):
    assert "error" in gm.apply(game, "sudo_win", {})


def test_no_game():
    assert "error" in gm.apply(None, "add_power", {})


# --- ресурсы -------------------------------------------------------------
def test_add_power_and_chips(game):
    p = game.players[0]
    gm.apply(game, "add_power", {"player_id": p.id, "amount": 7})
    gm.apply(game, "add_chips", {"player_id": p.id, "amount": 3})
    assert p.power_available == 7 and p.chipsines == 3
    gm.apply(game, "add_chips", {"player_id": p.id, "amount": -99})
    assert p.chipsines == 0            # в минус не уходим


def test_amount_is_clamped(game):
    p = game.players[0]
    gm.apply(game, "add_power", {"player_id": p.id, "amount": 10 ** 9})
    assert p.power_available == gm.MAX_DELTA


def test_bad_amount_is_ignored(game):
    p = game.players[0]
    gm.apply(game, "add_power", {"player_id": p.id, "amount": "хрень"})
    assert p.power_available == 0


def test_set_life_respects_max(game):
    p = game.players[0]
    gm.apply(game, "set_life", {"player_id": p.id, "value": 999})
    assert p.life == p.max_life


# --- смерть, воскрешение, приз ------------------------------------------
def test_kill_and_prize_transfer(game):
    holder, killer, _ = game.players
    holder.controls_prize = True
    game.prize_holder = holder.id
    game.undead_token_stack = []
    gm.apply(game, "kill", {"player_id": holder.id, "killer_id": killer.id})
    assert killer.controls_prize and not holder.controls_prize


def test_give_prize_is_exclusive(game):
    a, b, _ = game.players
    gm.apply(game, "give_prize", {"player_id": a.id})
    gm.apply(game, "give_prize", {"player_id": b.id})
    assert b.controls_prize and not a.controls_prize
    assert sum(p.controls_prize for p in game.players) == 1


def test_revive_uses_property_rules(game):
    p = game.players[0]
    p.property_id = "svo_6"
    p.life = 0
    gm.apply(game, "revive", {"player_id": p.id})
    assert p.life == MAX_LIFE


def test_set_loshara(game):
    p = game.players[0]
    gm.apply(game, "set_loshara", {"player_id": p.id, "value": True})
    assert p.is_loshara and p.max_life == 15
    gm.apply(game, "set_loshara", {"player_id": p.id, "value": False})
    assert not p.is_loshara


# --- жетоны и карты ------------------------------------------------------
def test_tokens_add_remove(game):
    p = game.players[0]
    gm.apply(game, "add_token", {"player_id": p.id, "token_id": "dk_1"})
    assert "dk_1" in p.death_tokens
    gm.apply(game, "remove_token", {"player_id": p.id, "token_id": "dk_1"})
    assert "dk_1" not in p.death_tokens
    assert "error" in gm.apply(game, "add_token", {"player_id": p.id, "token_id": "нет"})


def test_give_and_remove_card(game):
    p = game.players[0]
    gm.apply(game, "give_card", {"player_id": p.id, "card_id": "beast_ork",
                                 "destination": "hand"})
    assert "beast_ork" in p.hand
    gm.apply(game, "remove_card", {"player_id": p.id, "card_id": "beast_ork"})
    assert "beast_ork" not in p.hand
    assert "error" in gm.apply(game, "give_card", {"player_id": p.id, "card_id": "нет"})


def test_give_card_in_play(game):
    p = game.players[0]
    gm.apply(game, "give_card", {"player_id": p.id, "card_id": "place_dirty",
                                 "destination": "in_play"})
    assert "place_dirty" in p.zone_in_play


# --- стол ----------------------------------------------------------------
def test_set_turn(game):
    target = game.players[2]
    gm.apply(game, "set_turn", {"player_id": target.id})
    assert game.active_player.id == target.id


def test_clear_pending(game):
    game.pending_decision = {"player_id": "x", "options": []}
    gm.apply(game, "clear_pending", {})
    assert game.pending_decision is None


def test_refill_market(game):
    game.market.clear()
    gm.apply(game, "refill_market", {})
    assert len(game.market) == 5


def test_every_command_is_logged(game):
    p = game.players[0]
    before = len(game.logs)
    gm.apply(game, "add_chips", {"player_id": p.id, "amount": 1})
    assert len(game.logs) > before
    assert "Ведущий" in game.logs[-1] or "ведущего" in game.logs[-1]


def test_unknown_player(game):
    assert "error" in gm.apply(game, "add_power", {"player_id": "нетакого"})
