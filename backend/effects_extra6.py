"""Пакет 6: фамильяры, простые сокровища/твари/волшебники и их защиты.

Все обработчики здесь дописаны по тексту карт из cards.json.
Базовая мощь начисляется движком автоматически — тут только доп. эффекты.
"""
from __future__ import annotations

from .effects import effect, defense, activation


# ---------------------------------------------------------------------------
# ФАМИЛЬЯРЫ
# ---------------------------------------------------------------------------

@effect("fam_benz")
def _fam_benz(game, player, card, **kw):
    """+3 мощи. Следующей атаки в этот ход нельзя избежать."""
    player.next_attack_unavoidable = True
    game.log(f"{player.name}: следующей атаке в этот ход нельзя помешать")


@defense("fam_benz")
def _def_benz(game, defender, attacker, card):
    """Возьми 1 карту и перенаправь атаку на атакующего."""
    game.draw_cards(defender, 1)
    if attacker and attacker.is_alive():
        amount = 0
        attack = game.pending_attack
        if attack:
            amount = attack["targets"][attack["index"]]["amount"]
        if amount > 0:
            game.deal_damage(defender, attacker.id, amount, f"{card.name} (перенаправление)")
            game.log(f"{defender.name}: перенаправляет {amount} урона обратно в {attacker.name}")


@effect("fam_weaboo")
def _fam_weaboo(game, player, card, **kw):
    """Если под контролем есть легенда — атака: 8 урона, распределённых по врагам."""
    has_legend = any("Легенда" in game.cards[cid].types_for_matching
                     for cid in game.controlled_card_ids(player))
    if not has_legend or not kw.get("use_attack", True):
        return
    enemies = [p for p in game.enemies_of(player) if p.is_alive()]
    if not enemies:
        return
    base, extra = divmod(8, len(enemies))
    pairs = [(p, base + (1 if i < extra else 0)) for i, p in enumerate(enemies)]
    game.declare_variable_attack(player, card, pairs)


@effect("fam_notarius")
def _fam_notarius(game, player, card, **kw):
    pass  # только защита


@defense("fam_notarius")
def _def_notarius(game, defender, attacker, card):
    """Посмотри верхнюю карту основной колоды и можешь её купить бесплатно."""
    if not game.main_deck:
        return
    top_id = game.main_deck[-1]
    top = game.cards[top_id]
    options = [
        {"id": "take", "label": f"Забрать «{top.name}» бесплатно"},
        {"id": "skip", "label": "Оставить в колоде"},
    ]

    def resolve(choice: str):
        if choice == "take" and game.main_deck and game.main_deck[-1] == top_id:
            game.main_deck.pop()
            game.receive_card(defender, top_id, "discard")
            game.log(f"{defender.name}: забирает «{top.name}» бесплатно")

    game.request_decision(
        defender, card.name, f"Верхняя карта барахолки: {top.name}", options, resolve,
        revealed_cards=[{"id": top.id, "name": top.name}],
    )


@effect("fam_fatboy")
def _fam_fatboy(game, player, card, **kw):
    pass  # только защита


@defense("fam_fatboy")
def _def_fatboy(game, defender, attacker, card):
    """Можешь взять все «Палочки» из своей стопки сброса на руку."""
    sticks = [cid for cid in defender.discard if "Палочка" in game.cards[cid].name]
    if not sticks:
        return
    for cid in sticks:
        defender.discard.remove(cid)
        defender.hand.append(cid)
    game.log(f"{defender.name}: забирает {len(sticks)} «Палочек» из сброса на руку")


@effect("fam_jester")
def _fam_jester(game, player, card, **kw):
    """Атака: выбранный враг получает вялую палочку."""
    if not kw.get("use_attack", True):
        return
    target_id = kw.get("target_id")
    target = game.get_player(target_id)
    if not target:
        return

    def on_hit(hit_target, dead):
        game.give_weak_sticks(hit_target, 1, "discard")
        game.log(f"{hit_target.name}: получает вялую палочку от «{card.name}»")

    game.attack_target(player, card, target_id, 0, on_hit=on_hit)


@defense("fam_jester")
def _def_jester(game, defender, attacker, card):
    game.draw_cards(defender, 1)


@effect("fam_hostages")
def _fam_hostages(game, player, card, **kw):
    """Выбранный враг сбрасывает случайную карту."""
    target = game.get_player(kw.get("target_id"))
    if not target or not target.hand:
        return
    cid = game.rng.choice(target.hand)
    target.hand.remove(cid)
    target.discard.append(cid)
    game.log(f"{target.name}: сбрасывает случайную карту «{game.cards[cid].name}»")


@defense("fam_hostages")
def _def_hostages(game, defender, attacker, card):
    game.draw_cards(defender, 1)


@defense("fam_suitors")
def _def_suitors(game, defender, attacker, card):
    """Возьми 1 карту."""
    game.draw_cards(defender, 1)


@defense("fam_mescalito")
def _def_mescalito(game, defender, attacker, card):
    """Возьми 1 карту."""
    game.draw_cards(defender, 1)


@defense("leg_legdef")
def _def_legdef(game, defender, attacker, card):
    game.draw_cards(defender, 1)


# ---------------------------------------------------------------------------
# ВОЛШЕБНИКИ
# ---------------------------------------------------------------------------

@effect("wiz_koldunator")
def _wiz_koldunator(game, player, card, **kw):
    pass  # только +5 мощи, движок уже начислил


@effect("wiz_glistomage")
def _wiz_glistomage(game, player, card, **kw):
    pass  # только защита


@defense("wiz_glistomage")
def _def_glistomage(game, defender, attacker, card):
    """Можешь уничтожить 1 карту с руки."""
    if not defender.hand:
        return
    options = [{"id": cid, "label": game.cards[cid].name} for cid in defender.hand[:8]]
    options.append({"id": "skip", "label": "Ничего не уничтожать"})

    def resolve(choice: str):
        if choice != "skip":
            game.destroy_from_zone(defender, choice, "hand")

    game.request_decision(defender, card.name, "Уничтожить карту с руки?", options, resolve)


@effect("wiz_punks")
def _wiz_punks(game, player, card, **kw):
    pass  # только защита


@defense("wiz_punks")
def _def_punks(game, defender, attacker, card):
    """Возьми 1 карту, а атакующий отхватывает 2 урона."""
    game.draw_cards(defender, 1)
    if attacker and attacker.is_alive():
        game.deal_damage(defender, attacker.id, 2, card.name)


@activation("wiz_marmemage")
def _act_marmemage(game, player, card, **kw):
    """Уничтожь эту карту: перестань быть лошарой, затем накрути 7 жизней."""
    game.destroy_from_zone(player, card.id, "zone_in_play")
    if player.is_loshara:
        game.set_loshara(player, False)
    game.heal(player, 7)


# ---------------------------------------------------------------------------
# ЗАКЛИНАНИЯ
# ---------------------------------------------------------------------------

@effect("spell_liquidpun")
def _spell_liquidpun(game, player, card, **kw):
    """Атака: 7 урона выбранному врагу. Если он избежал — возьми 1 карту."""
    if not kw.get("use_attack", True):
        return
    target_id = kw.get("target_id")
    if not game.get_player(target_id):
        return
    before = {"life": game.get_player(target_id).life}

    def on_hit(target, dead):
        # Урон прошёл — карту не берём.
        before["hit"] = True

    game.attack_target(player, card, target_id, 7, on_hit=on_hit)
    if not before.get("hit"):
        game.draw_cards(player, 1)


@effect("spell_brotality")
def _spell_brotality(game, player, card, **kw):
    """В следующий раз, когда убьёшь врага в этот ход — он не получает жетон ЖДК."""
    player.brotality_active = True
    game.log(f"{player.name}: «{card.name}» — следующий убитый не получит жетон дохлого колдуна")


@effect("spell_lampwish")
def _spell_lampwish(game, player, card, **kw):
    pass  # защита-размещение обрабатывается движком как обычная защита


@defense("spell_lampwish")
def _def_lampwish(game, defender, attacker, card):
    """Карта кладётся на верх колоды вместо сброса."""
    if card.id in defender.discard:
        defender.discard.remove(card.id)
        defender.deck.append(card.id)
        game.log(f"{defender.name}: «{card.name}» уходит на верх колоды")


@activation("spell_magicspill")
def _act_magicspill(game, player, card, **kw):
    """Уничтожь эту карту: уничтожь 2 или меньше карт СО СВОЕЙ руки.

    В тексте карты опечатка («атака»), цели тут нет — чистится своя рука.
    """
    game.destroy_from_zone(player, card.id, "zone_in_play")
    if not player.hand:
        return

    def ask(remaining: int):
        if remaining <= 0 or not player.hand:
            return
        options = [{"id": cid, "label": game.cards[cid].name} for cid in player.hand[:10]]
        options.append({"id": "stop", "label": "Хватит"})

        def resolve(choice: str):
            if choice == "stop":
                return
            game.destroy_from_zone(player, choice, "hand")
            ask(remaining - 1)

        game.request_decision(
            player, card.name,
            f"Уничтожить карту со своей руки (осталось {remaining})", options, resolve,
        )

    ask(2)


# ---------------------------------------------------------------------------
# СОКРОВИЩА
# ---------------------------------------------------------------------------

@effect("treas_evilrak")
def _treas_evilrak(game, player, card, **kw):
    pass  # только +3 мощи


@effect("treas_chipsalochka")
def _treas_chipsalochka(game, player, card, **kw):
    """Можешь потратить 1 чипсину: атака — 10 урона выбранному колдуну."""
    if not kw.get("use_attack", True) or player.chipsines < 1:
        return
    target_id = kw.get("target_id")
    if not game.get_player(target_id):
        return
    player.chipsines -= 1
    game.log(f"{player.name}: тратит 1 чипсину на «{card.name}»")
    game.attack_target(player, card, target_id, 10)


@effect("treas_happybi")
def _treas_happybi(game, player, card, **kw):
    pass  # защита уже зарегистрирована в effects.py


@effect("treas_golddrop")
def _treas_golddrop(game, player, card, **kw):
    pass  # защита уже зарегистрирована в effects.py


@effect("treas_tsarbucks")
def _treas_tsarbucks(game, player, card, **kw):
    pass  # только защита


@defense("treas_tsarbucks")
def _def_tsarbucks(game, defender, attacker, card):
    """Потрать 1 жизнь и 1 чипсину, чтобы избежать атаки."""
    if defender.chipsines >= 1 and defender.life > 1:
        defender.chipsines -= 1
        defender.life -= 1
        game.log(f"{defender.name}: платит 1 жизнь и 1 чипсину за «{card.name}»")


# ---------------------------------------------------------------------------
# ТВАРИ
# ---------------------------------------------------------------------------

@effect("beast_beer")
def _beast_beer(game, player, card, **kw):
    pass  # только +4 мощи


@effect("beast_jellotit")
def _beast_jellotit(game, player, card, **kw):
    pass  # постоянка +1 мощь, учитывается в start_turn


@effect("beast_geek")
def _beast_geek(game, player, card, **kw):
    pass  # ПО считаются в конце игры


@effect("beast_twin")
def _beast_twin(game, player, card, **kw):
    pass  # только защита


@defense("beast_twin")
def _def_twin(game, defender, attacker, card):
    """Возьми другую тварь из своей стопки сброса на руку."""
    beasts = [cid for cid in defender.discard
              if "Тварь" in game.cards[cid].types_for_matching and cid != card.id]
    if not beasts:
        return
    cid = beasts[-1]
    defender.discard.remove(cid)
    defender.hand.append(cid)
    game.log(f"{defender.name}: возвращает тварь «{game.cards[cid].name}» на руку")


@activation("beast_jaba")
def _act_jaba(game, player, card, **kw):
    """Уничтожь эту карту: атака — выбранный колдун становится лошарой."""
    game.destroy_from_zone(player, card.id, "zone_in_play")
    target = game.get_player(kw.get("target_id"))
    if target:
        game.set_loshara(target, True)


@defense("beast_jaba")
def _def_jaba(game, defender, attacker, card):
    pass


# ---------------------------------------------------------------------------
# МЕСТА (постоянки)
# ---------------------------------------------------------------------------

@effect("place_vyaltower")
def _place_vyaltower(game, player, card, **kw):
    pass  # 2 вялые палочки выдаются при получении карты, +1 мощь в start_turn


@effect("place_dirty")
def _place_dirty(game, player, card, **kw):
    pass  # бонус к урону палочек учитывается в deal_damage


@effect("place_circus")
def _place_circus(game, player, card, **kw):
    pass  # +2 мощи лошаре в start_turn, ПО в конце игры


@effect("place_souv")
def _place_souv(game, player, card, **kw):
    pass  # выбор «легенда на верх колоды» — в receive_card
