"""Первые массовые Беспределы и Мегабеспределы."""
from .effects import effect


def all_players(game):
    return [p.id for p in game.players if p.is_alive()]


def destroy_options(game, player, zones):
    result = [{"id": "skip", "label": "Не уничтожать"}]
    for zone in zones:
        for cid in getattr(player, zone):
            result.append({"id": f"{zone}:{cid}", "label": game.cards[cid].name,
                           "detail": "Рука" if zone == "hand" else "Сброс"})
    return result


@effect("besp_2")
def besp_2(game, player, card, **kw):
    for target in game.players:
        target.discard.extend(target.deck)
        target.deck = []
    def apply(target, choice):
        if choice != "skip":
            zone, cid = choice.split(":", 1)
            game.destroy_from_zone(target, cid, zone)
    game.request_decision_sequence(
        game.players, "БЕСПРЕДЕЛ: чистка сброса", lambda p: "Колода сброшена. Уничтожь 1 карту из сброса или откажись.",
        lambda p: destroy_options(game, p, ["discard"]), apply,
    )


@effect("besp_4")
def besp_4(game, player, card, **kw):
    def apply(target, choice):
        if choice != "skip":
            if target.is_loshara:
                target.life -= 3
            zone, cid = choice.split(":", 1)
            game.destroy_from_zone(target, cid, zone)
    game.request_decision_sequence(
        game.players, "БЕСПРЕДЕЛ: уничтожение", lambda p: "Можешь уничтожить 1 карту с руки или из сброса. Лошара платит 3 жизни.",
        lambda p: destroy_options(game, p, ["hand", "discard"]), apply,
    )


@effect("besp_6")
def besp_6(game, player, card, **kw):
    def options(target):
        return [{"id":"damage","label":"Получить 5 урона"}, {"id":"redraw","label":"Сбросить руку и взять 5 карт"}]
    def apply(target, choice):
        if choice == "redraw":
            target.discard.extend(target.hand)
            target.hand=[]
            game.draw_cards(target, 5)
        else:
            game.deal_damage(player, target.id, 5, card.name, defendable=False)
    game.request_decision_sequence(game.players, "БЕСПРЕДЕЛ: выбор", lambda p: "Сбросить руку и взять 5 карт или отхватить 5 урона?", options, apply)


@effect("besp_11")
def besp_11(game, player, card, **kw):
    for target in game.players:
        target.chipsines += 1
    game.destroyed_pile.extend(game.legend_market)
    game.legend_market = []
    game._fill_legend_market_resolving()


@effect("besp_13")
def besp_13(game, player, card, **kw):
    def apply(target, choice):
        if choice == "yes":
            target.life = 10
            target.chipsines += 1
    game.request_decision_sequence(
        game.players, "БЕСПРЕДЕЛ: жизни за чипсину", lambda p: "Свести жизни к 10 и получить 1 чипсину?",
        lambda p: [{"id":"yes","label":"Свести жизни к 10, получить чипсину"},{"id":"no","label":"Отказаться"}], apply,
    )


@effect("besp_15")
def besp_15(game, player, card, **kw):
    for target in game.players:
        if not target.is_loshara:
            target.chipsines += 1
    game.log("БЕСПРЕДЕЛ: все не-лошары получают по чипсине")


@effect("besp_16")
def besp_16(game, player, card, **kw):
    living = [p for p in game.players if p.is_alive()]
    if not living:
        return
    lowest = min(p.life for p in living)
    for target in living:
        if target.life == lowest:
            target.is_loshara = True
            target.max_life = 15
            target.life = 15
    game.log("БЕСПРЕДЕЛ: самый хилый колдун становится лошарой")


@effect("besp_17")
def besp_17(game, player, card, **kw):
    game.declare_attack(player, card, all_players(game), 5)


@effect("besp_18")
def besp_18(game, player, card, **kw):
    revealed = {}
    for target in game.players:
        cards=[]
        for _ in range(2):
            if not target.deck:
                game.reshuffle_discard_into_deck(target)
            if target.deck:
                cards.append(target.deck.pop())
        target.discard.extend(cards)
        revealed[target.id] = cards
    def options(target):
        cards = revealed.get(target.id, [])
        if not cards:
            return [{"id":"keep","label":"Нечего уничтожать"}]
        return [{"id":"destroy","label":"Уничтожить обе карты"},{"id":"keep","label":"Оставить обе в сбросе"}]
    def apply(target, choice):
        if choice == "destroy":
            for cid in revealed.get(target.id, []):
                if cid in target.discard:
                    game.destroy_from_zone(target, cid, "discard")
    game.request_decision_sequence(game.players, "БЕСПРЕДЕЛ: две верхние", lambda p: "Уничтожить обе сброшенные карты или ни одной?", options, apply)


@effect("mega_2")
def mega_2(game, player, card, **kw):
    for target in game.players:
        game.give_weak_sticks(target, 3, "hand")


@effect("mega_6")
def mega_6(game, player, card, **kw):
    for target in game.players:
        if target.is_alive():
            target.life = min(target.life, 5)
    game.log("МЕГАБЕСПРЕДЕЛ: жизни всех колдунов сведены к 5")


@effect("mega_7")
def mega_7(game, player, card, **kw):
    for target in game.players:
        target.chipsines += len(target.death_tokens)
    game.log("МЕГАБЕСПРЕДЕЛ: чипсины за каждый ЖДК")
