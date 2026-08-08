"""
Реестр эффектов карт.

Базовая механика (мощь при розыгрыше, стоимость, ПО, тип, постоянка) уже
обрабатывается движком автоматически на основе cards.json — это ничего
не стоит переписывать руками.

Здесь регистрируются ТОЛЬКО дополнительные текстовые эффекты конкретных
карт ("Возьми 1 карту", "Атака: нанеси 5 урона...", и т.п.).

Если для card.id обработчика нет — движок просто применит базовую механику
(+ мощь) и залогирует, что текстовый эффект карты пока не реализован.
Это осознанный компромисс: 129 карт руками за один присест не переписать,
зато игра не падает и её можно тестировать прямо сейчас. Обработчики
дописываются по одному, инкрементально.
"""
from __future__ import annotations
from typing import Callable

EFFECT_REGISTRY: dict[str, Callable] = {}


def effect(card_id: str):
    def deco(fn: Callable):
        EFFECT_REGISTRY[card_id] = fn
        return fn
    return deco


def get_effect(card_id: str):
    return EFFECT_REGISTRY.get(card_id)


# ---------------------------------------------------------------------------
# Затравки (стартовые карты) — эти есть в руке у всех с первого хода,
# поэтому реализованы полностью в первую очередь.
# ---------------------------------------------------------------------------

@effect("start_znak")
def _znak(game, player, card, **kw):
    pass  # "+1 мощь" — уже применено движком автоматически


@effect("start_pshik")
def _pshik(game, player, card, **kw):
    pass  # эффекта нет


@effect("start_syrpal")
def _syrnaya(game, player, card, **kw):
    target_id = kw.get("target_id", player.id)  # можно и себя (стр. 17)
    dead = game.deal_damage(source=player, target_id=target_id, amount=1,
                             card_name=card.name, defendable=True)
    if dead and game.last_damage_target_id == target_id:
        target = game.get_player(target_id)
        if target.just_died:
            player.chipsines += 3
            game.log(f"{player.name}: {card.name} убила {target.name}, +3 чипсины")


@effect("start_hrenal")
def _hrenalochka(game, player, card, **kw):
    target_id = kw.get("target_id", player.id)  # можно себя, т.к. "колдун"
    game.deal_damage(source=player, target_id=target_id, amount=1,
                      card_name=card.name, defendable=True, unavoidable=False)
    target = game.get_player(target_id)
    if target.just_died:
        give_ids = kw.get("give_card_ids", [])[:2]
        for cid in give_ids:
            if cid in player.discard:
                player.discard.remove(cid)
                target.hand.append(cid)
        game.log(f"{player.name}: {card.name} — передал(а) {len(give_ids)} карт(ы) из сброса воскресшему")


# ---------------------------------------------------------------------------
# Шальная магия / Вялая палочка — общие правила, а не отдельная карта
# ---------------------------------------------------------------------------

@effect("spec_wild")
def _wild_magic(game, player, card, **kw):
    choice = kw.get("choice", "power")  # "power" или "steal"
    if choice == "power":
        player.power_available += 2
        game.log(f"{player.name}: Шальная магия -> +2 мощи")
    else:
        target_id = kw.get("target_id")
        target = game.get_player(target_id)
        if not target or not target.deck:
            game.reshuffle_discard_into_deck(target) if target else None
        if target and target.deck:
            top_id = target.deck.pop()
            top_card = game.cards[top_id]
            game.log(f"{player.name}: Шальная магия -> разыгрывает {top_card.name} из колоды {target.name}")
            game.apply_card_effect(player, top_card, **kw)
            if top_card.postoyanka:
                player.in_play.append(top_id)
            else:
                target.discard.append(top_id)


@effect("spec_vyal")
def _vyal(game, player, card, **kw):
    pass  # эффекта нет, -1 ПО считается при подсчёте очков


# ---------------------------------------------------------------------------
# Дохляки (Чак/Жак/Ермак/Зак/Исаак) — 5 одинаковых по механике карт,
# отличаются только именем/картинкой. Стоимость 1, 1 ПО, при розыгрыше
# считаются жетоном ЖДК и дают чипсину за каждый такой жетон под контролем
# (упрощённая версия правила — без пересчёта в конце каждого хода).
# ---------------------------------------------------------------------------

def _dohlyak_effect(game, player, card, **kw):
    count = len(player.death_tokens) + 1  # сама карта тоже считается жетоном
    player.chipsines += count
    game.log(f"{player.name}: {card.name} — получает {count} чипсины (жетонов ЖДК: {count})")


for _sdk_id in ["sdk_1", "sdk_2", "sdk_3", "sdk_4", "sdk_5"]:
    EFFECT_REGISTRY[_sdk_id] = _dohlyak_effect


# ---------------------------------------------------------------------------
# Примеры реализации для основной колоды — разных паттернов текста,
# чтобы дальнейшие карты добавлялись по аналогии.
# ---------------------------------------------------------------------------

@effect("beast_ork")
def _ork(game, player, card, **kw):
    has_other_beast = any(game.cards[c].type == "Тварь" for c in player.in_play_this_turn if c != card.id) \
        or any(game.cards[c].type == "Тварь" for c in player.zone_in_play)
    if has_other_beast:
        player.power_available += 2
        game.log(f"{player.name}: {card.name} — доп. тварь на столе, +2 мощи")


@effect("spell_brainstrom")
def _mozgoshtorm(game, player, card, **kw):
    game.draw_cards(player, 2)


@effect("place_dlan")
def _dlan_tvorca(game, player, card, **kw):
    pass  # постоянка "+1 к пределу руки" учитывается при подсчёте лимита руки


@effect("wiz_berserk")
def _berserk(game, player, card, **kw):
    target_id = kw.get("target_id")
    game.deal_damage(source=player, target_id=target_id, amount=6,
                      card_name=card.name, defendable=True)


@effect("spell_dirtwind")
def _musorny_veter(game, player, card, **kw):
    destroy_id = kw.get("destroy_from_discard_id")
    if destroy_id and destroy_id in player.discard:
        player.discard.remove(destroy_id)
        game.destroyed_pile.append(destroy_id)
    game.declare_attack(player, card, targets="all_enemies", amount=5)


@effect("beast_peepoo")
def _nechistaya_sila(game, player, card, **kw):
    game.draw_cards(player, 1)
    game.declare_attack(player, card, targets="left_right", amount=7)
