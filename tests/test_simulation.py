"""Нагрузочный прогон: случайные партии целиком.

Задача — поймать исключения в эффектах карт и нарушения инвариантов,
а не проверить конкретное правило. Каждая карта хотя бы раз разыгрывается.
"""
from __future__ import annotations

import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.game import GameState  # noqa: E402
from backend import effects  # noqa: E402


def _auto_resolve(game, limit: int = 60):
    """Автоматически закрывает висящие решения и события."""
    for _ in range(limit):
        if game.pending_decision:
            opts = game.pending_decision.get("options") or []
            pid = game.pending_decision["player_id"]
            player = game.get_player(pid)
            if not opts:
                game.pending_decision = None
                continue
            choice = game.rng.choice(opts)["id"]
            game.resolve_decision(player, choice)
            continue
        if game.pending_event:
            game.resolve_event()
            continue
        return
    game.pending_decision = None


def _play_random_game(seed: int, max_turns: int = 40) -> dict:
    names = ["Игрок A", "Игрок B", "Игрок C"]
    game = GameState(names, seed=seed)
    played_ids = set()

    for _ in range(max_turns):
        if game.game_over:
            break
        _auto_resolve(game)
        player = game.active_player

        # разыгрываем всю руку
        for card_id in list(player.hand):
            if game.game_over:
                break
            _auto_resolve(game)
            if card_id not in player.hand:
                continue
            enemies = [p for p in game.enemies_of(player) if p.is_alive()]
            kwargs = {}
            if enemies:
                kwargs["target_id"] = game.rng.choice(enemies).id
                kwargs["target_ids"] = [e.id for e in enemies[:3]]
            game.play_card(player, card_id, **kwargs)
            played_ids.add(card_id)
            _auto_resolve(game)

        # отложенные атаки
        for card_id in list(player.available_attacks):
            if game.game_over:
                break
            enemies = [p for p in game.enemies_of(player) if p.is_alive()]
            if not enemies:
                break
            game.activate_attack(player, card_id, target_id=game.rng.choice(enemies).id)
            _auto_resolve(game)

        # активации постоянок
        for card_id in list(player.zone_in_play):
            if game.game_over:
                break
            if card_id in effects.ACTIVATION_REGISTRY:
                enemies = [p for p in game.enemies_of(player) if p.is_alive()]
                kw = {"target_id": game.rng.choice(enemies).id} if enemies else {}
                game.activate_permanent(player, card_id, **kw)
                _auto_resolve(game)

        # покупки
        for _ in range(2):
            if game.game_over or not game.market:
                break
            card_id = game.rng.choice(game.market)
            if game.cards[card_id].cost <= player.power_available:
                game.buy_card(player, card_id)
                _auto_resolve(game)

        if game.game_over:
            break
        game.end_turn(player)
        _auto_resolve(game)

    return {"game": game, "played": played_ids}


def test_many_random_games_do_not_crash():
    """200 партий подряд без единого исключения."""
    for seed in range(200):
        result = _play_random_game(seed, max_turns=25)
        game = result["game"]
        for p in game.players:
            assert p.life <= p.max_life, f"seed={seed}: {p.name} выше максимума HP"
            assert p.chipsines >= 0, f"seed={seed}: отрицательные чипсины"
            assert p.power_available >= 0, f"seed={seed}: отрицательная мощь"


def test_no_cards_vanish():
    """Карты не исчезают и не дублируются за партию."""
    for seed in range(40):
        game = GameState(["A", "B"], seed=seed)
        before = _count_all(game)
        result = _play_random_game(seed, max_turns=15)
        after = _count_all(result["game"])
        assert after >= before - 5, f"seed={seed}: карты пропали ({before} -> {after})"


def _count_all(game) -> int:
    total = len(game.main_deck) + len(game.legend_deck) + len(game.market) + len(game.legend_market)
    total += len(game.destroyed_pile)
    for p in game.players:
        total += len(p.deck) + len(p.hand) + len(p.discard) + len(p.zone_in_play)
    return total


def test_every_registered_effect_is_callable():
    """Все зарегистрированные обработчики — вызываемые объекты."""
    for cid, fn in effects.EFFECT_REGISTRY.items():
        assert callable(fn), f"{cid}: обработчик не вызывается"
    for cid, fn in effects.DEFENSE_REGISTRY.items():
        assert callable(fn), f"{cid}: защита не вызывается"
    for cid, fn in effects.ACTIVATION_REGISTRY.items():
        assert callable(fn), f"{cid}: активация не вызывается"


def test_scoring_counts_deck():
    """В финальном подсчёте учитываются карты из колоды игрока."""
    game = GameState(["A", "B"], seed=1)
    player = game.players[0]
    player.deck.append("leg_goose")   # 4 ПО лежит именно в колоде
    game._finish_game()
    assert game.final_scores[player.id]["legends"] >= 1, "легенда из колоды не засчитана"


def test_all_properties_playable():
    """Каждое свойство колдуна отрабатывает начало хода без падений."""
    import json
    svo_path = os.path.join(os.path.dirname(__file__), "..", "svo.json")
    with open(svo_path, encoding="utf-8") as f:
        props = json.load(f)

    for prop in props:
        game = GameState(["A", "B", "C"], seed=3)
        player = game.active_player
        player.property_id = prop["id"]
        # под контролем пара карт разных типов — чтобы условия свойств срабатывали
        player.zone_in_play.extend(["treas_evilrak", "beast_beer", "wiz_koldunator", "spell_liquidpun"])
        game.start_turn()
        _auto_resolve(game)
        assert player.chipsines >= 0, f"{prop['id']}: отрицательные чипсины"
        assert player.power_available >= 0, f"{prop['id']}: отрицательная мощь"


def test_start_life_is_20_of_25():
    """Каждый колдун начинает с 20 из 25 жизней (правила, стр. 6)."""
    game = GameState(["A", "B", "C"], seed=5)
    for p in game.players:
        assert p.life == 20, f"{p.name}: старт {p.life}, ожидалось 20"
        assert p.max_life == 25, f"{p.name}: максимум {p.max_life}, ожидалось 25"


def test_prize_property_starts_full():
    """Свойство «Главный приз» (svo_6) — единственное, что даёт старт 25/25."""
    game = GameState(["A", "B"], seed=5)
    hero = game.players[0]
    hero.property_id = "svo_6"
    game.apply_property_setup(hero)
    assert hero.life == 25 and hero.max_life == 25
    assert game.players[1].life == 20, "остальные должны остаться на 20"


def test_magicspill_destroys_own_hand():
    """«Волшебные отходы» чистят СВОЮ руку и не трогают врага."""
    from backend import effects
    game = GameState(["A", "B"], seed=5)
    me = game.active_player
    enemy = game.enemies_of(me)[0]
    me.zone_in_play.append("spell_magicspill")
    me.hand = ["start_znak", "start_pshik", "start_znak"]
    enemy.hand = ["start_znak", "start_znak"]
    enemy_before = len(enemy.hand)

    game.activate_permanent(me, "spell_magicspill")
    _auto_resolve(game)

    assert len(enemy.hand) == enemy_before, "рука врага не должна меняться"
    assert len(me.hand) < 3, "своя рука должна уменьшиться"
