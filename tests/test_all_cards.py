"""Каждая карта в игре разыгрывается хотя бы раз — движок не должен падать.

Случайные партии задевают только часть колоды, поэтому здесь карты
подставляются в руку принудительно.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.game import GameState  # noqa: E402
from backend import effects  # noqa: E402
from backend.models import load_all_cards  # noqa: E402

ALL_CARDS = load_all_cards()


def _fresh_game(seed: int = 7) -> GameState:
    return GameState(["Тестер", "Враг 1", "Враг 2"], seed=seed)


def _drain(game, limit: int = 40):
    """Закрывает висящие решения/события, выбирая первый вариант."""
    for _ in range(limit):
        if game.pending_decision:
            opts = game.pending_decision.get("options") or []
            player = game.get_player(game.pending_decision["player_id"])
            if not opts:
                game.pending_decision = None
                continue
            game.resolve_decision(player, opts[0]["id"])
            continue
        if game.pending_event:
            game.resolve_event()
            continue
        break


@pytest.mark.parametrize("card_id", sorted(ALL_CARDS))
def test_card_plays_without_crash(card_id):
    """Карта разыгрывается и не роняет движок."""
    game = _fresh_game()
    player = game.active_player
    enemies = [p for p in game.enemies_of(player) if p.is_alive()]

    player.hand.append(card_id)
    player.power_available += 20
    player.chipsines += 5

    # use_attack движок подставляет сам — передавать его нельзя.
    kwargs = {
        "target_id": enemies[0].id,
        "target_ids": [e.id for e in enemies],
    }
    game.play_card(player, card_id, **kwargs)
    _drain(game)

    for p in game.players:
        assert p.life <= p.max_life, f"{card_id}: {p.name} превысил максимум HP"
        assert p.chipsines >= 0, f"{card_id}: отрицательные чипсины"
        assert p.power_available >= 0, f"{card_id}: отрицательная мощь"


@pytest.mark.parametrize("card_id", sorted(effects.DEFENSE_REGISTRY))
def test_defense_runs_without_crash(card_id):
    """Защитный эффект отрабатывает без исключений."""
    game = _fresh_game()
    defender = game.players[0]
    attacker = game.players[1]
    card = ALL_CARDS[card_id]

    defender.hand.append(card_id)
    defender.discard.extend(["start_znak", "start_pshik"])
    game._queue_attack(attacker, ALL_CARDS["start_syrpal"], [defender], 3, False, None)

    effects.apply_defense(game, defender, attacker, card)
    _drain(game)

    assert defender.life <= defender.max_life
    assert attacker.life <= attacker.max_life


@pytest.mark.parametrize("card_id", sorted(effects.ACTIVATION_REGISTRY))
def test_activation_runs_without_crash(card_id):
    """Активация постоянки отрабатывает без исключений."""
    game = _fresh_game()
    player = game.active_player
    enemy = game.enemies_of(player)[0]

    player.zone_in_play.append(card_id)
    result = game.activate_permanent(player, card_id, target_id=enemy.id)
    _drain(game)

    assert not result.get("error"), f"{card_id}: {result.get('error')}"
    for p in game.players:
        assert p.life <= p.max_life
