"""Пакет 7: легенды."""
from __future__ import annotations

from .effects import effect, defense, activation


@effect("leg_harik")
def _leg_harik(game, player, card, **kw):
    """Атака: 10 урона левому или правому врагу. Если подох — атакуй следующего."""
    if not kw.get("use_attack", True):
        return
    order = [p for p in game._resolve_target_group(player, "left_right") if p.is_alive()]
    if not order:
        return
    target_id = kw.get("target_id") or order[0].id
    first = game.get_player(target_id) or order[0]

    def chain(target, dead):
        if not dead:
            return
        idx = game.players.index(target)
        for step in range(1, len(game.players)):
            nxt = game.players[(idx + step) % len(game.players)]
            if nxt.id != player.id and nxt.is_alive():
                game.log(f"{card.name}: цепная атака переходит на {nxt.name}")
                game.attack_target(player, card, nxt.id, 10)
                return

    game.attack_target(player, card, first.id, 10, on_hit=chain)


@effect("leg_vener")
def _leg_vener(game, player, card, **kw):
    """Атака: можешь обменяться жизнями и/или статусом лошары."""
    if not kw.get("use_attack", True):
        return
    target = game.get_player(kw.get("target_id"))
    if not target:
        return
    options = [
        {"id": "life", "label": "Обменяться жизнями"},
        {"id": "loshara", "label": "Обменяться статусом лошары"},
        {"id": "both", "label": "Обменять и жизни, и статус"},
        {"id": "skip", "label": "Ничего не менять"},
    ]

    def resolve(choice: str):
        if choice in ("life", "both"):
            player.life, target.life = target.life, player.life
            player.life = min(player.life, player.max_life)
            target.life = min(target.life, target.max_life)
            game.log(f"{player.name} и {target.name} обменялись жизнями")
        if choice in ("loshara", "both"):
            mine, theirs = player.is_loshara, target.is_loshara
            game.set_loshara(player, theirs)
            game.set_loshara(target, mine)
            game.log(f"{player.name} и {target.name} обменялись статусом лошары")

    game.request_decision(player, card.name, f"Цель: {target.name}", options, resolve)


@effect("leg_goose")
def _leg_goose(game, player, card, **kw):
    pass  # ПО считаются в конце игры


@effect("leg_lover")
def _leg_lover(game, player, card, **kw):
    """Атака: отдай 1 свой жетон ЖДК выбранному колдуну, он применяет эффект."""
    if not kw.get("use_attack", True) or not player.death_tokens:
        return
    target = game.get_player(kw.get("target_id"))
    if not target:
        return
    token_id = player.death_tokens.pop()
    target.death_tokens.append(token_id)
    name = game.zhdk.get(token_id, {}).get("name", token_id)
    game.log(f"{player.name}: отдаёт жетон «{name}» игроку {target.name}")
    game._resolve_death_token(target, token_id, player)


@effect("leg_mortal")
def _leg_mortal(game, player, card, **kw):
    """Атака: убей выбранного врага."""
    if not kw.get("use_attack", True):
        return
    target = game.get_player(kw.get("target_id"))
    if not target:
        return
    game.attack_target(player, card, target.id, max(1, target.life))


@effect("leg_captain")
def _leg_captain(game, player, card, **kw):
    """Атака: раскрой 4 верхние карты колоды врага, сыграй 1, остальные сбрось."""
    if not kw.get("use_attack", True):
        return
    target = game.get_player(kw.get("target_id"))
    if not target:
        return
    if len(target.deck) < 4:
        game.reshuffle_discard_into_deck(target)
    revealed = [target.deck.pop() for _ in range(min(4, len(target.deck)))]
    if not revealed:
        return
    options = [{"id": cid, "label": game.cards[cid].name} for cid in revealed]

    def resolve(choice: str):
        if choice in revealed:
            chosen = game.cards[choice]
            game.log(f"{player.name}: играет «{chosen.name}» из колоды {target.name}")
            game.apply_card_effect(player, chosen, **kw)
        for cid in revealed:
            target.discard.append(cid)

    game.request_decision(
        player, card.name, f"Карты из колоды {target.name}", options, resolve,
        revealed_cards=[game.card_public(c) for c in revealed],
    )


@effect("leg_epicvyal")
def _leg_epicvyal(game, player, card, **kw):
    """Атака: 7 урона. Если подох — можешь дать ему до 3 вялых палочек."""
    if not kw.get("use_attack", True):
        return
    target_id = kw.get("target_id")
    if not game.get_player(target_id):
        return

    def on_hit(target, dead):
        if dead:
            game.give_weak_sticks(target, 3, "discard")
            game.log(f"{target.name}: получает 3 вялые палочки")

    game.attack_target(player, card, target_id, 7, on_hit=on_hit)


@effect("leg_minigun")
def _leg_minigun(game, player, card, **kw):
    """Три отдельные атаки по 7 урона."""
    if not kw.get("use_attack", True):
        return
    ids = kw.get("target_ids") or ([kw.get("target_id")] if kw.get("target_id") else [])
    targets = [game.get_player(i) for i in ids if game.get_player(i)]
    if not targets:
        return
    pairs = [(t, 7) for t in targets[:3]]
    game.declare_variable_attack(player, card, pairs)


@effect("leg_loshash")
def _leg_loshash(game, player, card, **kw):
    pass  # защита уже зарегистрирована


@effect("leg_sexlight")
def _leg_sexlight(game, player, card, **kw):
    """Постоянка: +1 мощь за каждый жетон ЖДК.

    Начисляем СРАЗУ при выкладывании — игрок не должен ждать следующего
    хода, чтобы увидеть эффект. В start_turn мощь начислится снова.
    """
    bonus = len(player.death_tokens)
    if bonus:
        player.power_available += bonus
        game.log(f"{player.name}: «{card.name}» +{bonus} мощи за жетоны "
                 f"(всего {player.power_available})")


@effect("leg_tronado")
def _leg_tronado(game, player, card, **kw):
    pass  # бонус мощи за первый урон — в deal_damage


@effect("leg_park")
def _leg_park(game, player, card, **kw):
    pass  # лечение за нанесённый урон — в deal_damage


@effect("leg_arena")
def _leg_arena(game, player, card, **kw):
    pass  # удвоение урона — в deal_damage


@effect("leg_viagrus")
def _leg_viagrus(game, player, card, **kw):
    """Постоянка: в начале хода можешь взять вялую палочку из стопки."""
    pass  # выдача — в start_turn


@effect("leg_tower")
def _leg_tower(game, player, card, **kw):
    pass  # текста у карты нет


@activation("leg_throne")
def _act_throne(game, player, card, **kw):
    """Атака: урон равен стоимости другой карты под твоим контролем."""
    target = game.get_player(kw.get("target_id"))
    if not target:
        return
    controlled = [cid for cid in game.controlled_card_ids(player) if cid != card.id]
    if not controlled:
        return
    best = max(controlled, key=lambda cid: game.cards[cid].cost)
    amount = game.cards[best].cost
    game.log(f"{card.name}: урон {amount} по стоимости «{game.cards[best].name}»")
    game.attack_target(player, card, target.id, amount)
