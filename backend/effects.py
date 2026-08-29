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
DEFENSE_REGISTRY: dict[str, Callable] = {}
ACTIVATION_REGISTRY: dict[str, Callable] = {}


def activation(card_id: str):
    def deco(fn: Callable):
        ACTIVATION_REGISTRY[card_id] = fn
        return fn
    return deco


def apply_activation(game, player, card, **kwargs):
    handler = ACTIVATION_REGISTRY.get(card.id)
    if not handler:
        return {"error": "У этой постоянки пока нет активируемого эффекта"}
    handler(game, player, card, **kwargs)
    return {"ok": True}


def defense(card_id: str):
    def deco(fn: Callable):
        DEFENSE_REGISTRY[card_id] = fn
        return fn
    return deco


def apply_defense(game, defender, attacker, card):
    handler = DEFENSE_REGISTRY.get(card.id)
    if handler:
        handler(game, defender, attacker, card)


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
    if not kw.get("use_attack", True):
        return
    target_id = kw.get("target_id", player.id)  # можно и себя (стр. 17)
    def reward(target, dead):
        if dead:
            player.chipsines += 3
            game.log(f"{player.name}: {card.name} убила {target.name}, +3 чипсины")
    game.attack_target(player, card, target_id, 1, on_hit=reward)


@effect("start_hrenal")
def _hrenalochka(game, player, card, **kw):
    if not kw.get("use_attack", True):
        return
    target_id = kw.get("target_id", player.id)  # можно себя, т.к. "колдун"
    def give_to_revived(target, dead):
        if not dead:
            return
        give_ids = kw.get("give_card_ids", [])[:2]
        for cid in give_ids:
            if cid in player.discard:
                player.discard.remove(cid)
                target.hand.append(cid)
        game.log(f"{player.name}: {card.name} — передал(а) {len(give_ids)} карт(ы) воскресшему")
    game.attack_target(player, card, target_id, 1, on_hit=give_to_revived)


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
        if not target:
            return
        if not target.deck:
            game.reshuffle_discard_into_deck(target)
        if not target.deck:
            game.log(f"{player.name}: у {target.name} нет карт в колоде — красть нечего")
            return
        top_id = target.deck.pop()
        top_card = game.cards[top_id]
        game.log(f"{player.name}: Шальная магия крадёт «{top_card.name}» из колоды {target.name}")
        # Показываем украденную карту всем: она летит из колоды врага на стол.
        game.emit_visual_event("play", player, [top_id], "deck", "table")
        # Карта считается сыгранной этим игроком: работает весь ход целиком.
        player.in_play_this_turn.append(top_id)
        player.power_available += top_card.power
        if top_card.power:
            game.log(f"{player.name}: «{top_card.name}» +{top_card.power} мощи (всего {player.power_available})")
        game.apply_card_effect(player, top_card, **kw)
        # В конце хода вернётся владельцу — помечаем, чтобы end_turn знал куда.
        player.borrowed_cards.append((top_id, target.id))


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
        game.log(f"{player.name}: {card.name} — есть ещё тварь, +2 мощи (всего {player.power_available})")


@effect("spell_brainstrom")
def _mozgoshtorm(game, player, card, **kw):
    game.draw_cards(player, 2)


@effect("place_dlan")
def _dlan_tvorca(game, player, card, **kw):
    pass  # постоянка "+1 к пределу руки" учитывается при подсчёте лимита руки


@effect("wiz_berserk")
def _berserk(game, player, card, **kw):
    if not kw.get("use_attack", True):
        return
    target_id = kw.get("target_id")
    game.attack_target(player, card, target_id, 6)


@effect("spell_dirtwind")
def _musorny_veter(game, player, card, **kw):
    if not kw.get("attack_only", False):
        destroy_id = kw.get("destroy_from_discard_id")
        if destroy_id and destroy_id in player.discard:
            player.discard.remove(destroy_id)
            game.destroyed_pile.append(destroy_id)
    if kw.get("use_attack", True):
        game.declare_attack(player, card, targets="all_enemies", amount=5)


@effect("beast_peepoo")
def _nechistaya_sila(game, player, card, **kw):
    if not kw.get("attack_only", False):
        game.draw_cards(player, 1)
    if kw.get("use_attack", True):
        game.declare_attack(player, card, targets="left_right", amount=7)

# ---------------------------------------------------------------------------
# Простые эффекты добора и базовой колоды.
# ---------------------------------------------------------------------------
@effect("fam_suitors")
def _suitors(game, player, card, **kw):
    if not kw.get("attack_only", False): game.draw_cards(player, 1)

@effect("fam_family")
def _family(game, player, card, **kw):
    if not kw.get("attack_only", False): game.draw_cards(player, 1)

@effect("fam_conduct")
def _conduct(game, player, card, **kw):
    if not kw.get("attack_only", False): game.draw_cards(player, 2)

@effect("fam_mescalito")
def _mescalito(game, player, card, **kw):
    if not kw.get("attack_only", False):
        game.draw_cards(player, 1); player.power_available += len(player.death_tokens)

@effect("treas_witchgift")
def _witchgift(game, player, card, **kw):
    if not kw.get("attack_only", False):
        game.draw_cards(player, 1); player.power_available += len(player.zone_in_play)

@effect("leg_epicheart")
def _epicheart(game, player, card, **kw):
    if not kw.get("attack_only", False):
        game.draw_cards(player, 1); player.chipsines += 3

@effect("spell_endbro")
def _endbro(game, player, card, **kw):
    if kw.get("attack_only", False): return
    game.draw_cards(player, 1)
    options=[{"id":p.id,"label":p.name,"detail":f"Рука: {len(p.hand)} · Колода: {len(p.deck)}"} for p in game.players if p.id != player.id]
    # В одиночной тестовой партии другого колдуна нет: только собственный добор.
    if not options:
        return
    def give_card(target_id):
        target=game.get_player(target_id)
        if target: game.draw_cards(target,1)
    game.request_decision(player,"Кому дать карту?","Ты уже взял(а) 1 карту. Выбери колдуна, который также возьмёт 1 карту.",options,give_card)

# Регистрируем следующий пакет после создания decorator/registry.
from . import effects_extra  # noqa: E402,F401
from . import effects_extra2  # noqa: E402,F401

# Базовые эффекты защит. Сама отмена атаки выполняется движком; здесь только последствия.
@defense("wiz_berserk")
def _def_berserk(game, defender, attacker, card):
    game.draw_cards(defender, 1)

@defense("wiz_sheriff")
def _def_sheriff(game, defender, attacker, card):
    game.draw_cards(defender, 2)

@defense("treas_happybi")
def _def_happybi(game, defender, attacker, card):
    game.draw_cards(defender, 1)
    defender.chipsines += 1

@defense("treas_golddrop")
def _def_golddrop(game, defender, attacker, card):
    defender.chipsines += 2

@defense("fam_family")
def _def_family(game, defender, attacker, card):
    game.draw_cards(defender, 2)

@defense("fam_weaboo")
def _def_weaboo(game, defender, attacker, card):
    game.draw_cards(defender, 1)

@defense("leg_loshash")
def _def_loshash(game, defender, attacker, card):
    game.draw_cards(defender, 3)

@defense("fam_conduct")
def _def_conduct(game, defender, attacker, card):
    game.draw_cards(defender, 1)
from . import effects_extra3  # noqa: E402,F401
from . import effects_extra4  # noqa: E402,F401
from . import effects_extra5  # noqa: E402,F401
from . import effects_extra6  # noqa: E402,F401
from . import effects_extra7  # noqa: E402,F401
