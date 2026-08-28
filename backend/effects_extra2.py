"""Карты с простыми выборами и разбором колоды/сброса."""
from .effects import effect


def _brief(game, cid):
    c = game.cards[cid]
    return {"id":c.id,"name":c.name,"type":c.type,"cost":c.cost,"power":c.power,"vp":c.vp,"has_attack":c.has_attack,"text":c.full_text}


def _destroy_choice(game, player, title, text, zones, after=None):
    options = [{"id": "skip", "label": "Не уничтожать"}]
    for zone in zones:
        for cid in getattr(player, zone):
            options.append({"id": f"{zone}:{cid}", "label": game.cards[cid].name, "detail": "Рука" if zone == "hand" else "Сброс"})
    def resolve(choice):
        if choice != "skip":
            zone, cid = choice.split(":", 1)
            game.destroy_from_zone(player, cid, zone)
        if after:
            after()
    game.request_decision(player, title, text, options, resolve)


@effect("beast_spineeaters")
def spineeaters(game, player, card, **kw):
    if game.count_controlled_type(player, "Тварь", card.id) >= 1 and not kw.get("attack_only", False):
        _destroy_choice(game, player, "Спиногрызогрызы", "Есть ещё одна тварь. Можешь уничтожить карту с руки или из сброса.", ["hand", "discard"])


@effect("spell_poopie")
def poopie(game, player, card, **kw):
    if kw.get("attack_only", False):
        return
    if not player.deck:
        game.reshuffle_discard_into_deck(player)
    if not player.deck:
        return
    cid = player.deck.pop()
    revealed = game.cards[cid]
    options = [
        {"id": "destroy", "label": "Уничтожить «%s»" % revealed.name},
        {"id": "power", "label": "+%s мощи" % revealed.cost, "detail": "Вернуть карту в сброс"},
    ]
    def resolve(choice):
        if choice == "destroy":
            game.destroyed_pile.append(cid)
        else:
            player.discard.append(cid)
            player.power_available += revealed.cost
    game.request_decision(player, "Говна-пирога", f"Раскрыта карта «{revealed.name}» стоимостью {revealed.cost}.", options, resolve, revealed_cards=[_brief(game, cid)])


@effect("treas_totemhelm")
def totemhelm(game, player, card, **kw):
    if kw.get("attack_only", False) or player.chipsines < 1:
        return
    # Опциональная оплата чипсины: сначала выбор «использовать / нет».
    def choose_use(choice):
        if choice != "yes":
            return
        player.chipsines -= 1
        _destroy_choice(game, player, "Шлем-тотем", "Выбери карту на руке или в сбросе для уничтожения.", ["hand", "discard"])
    game.request_decision(player, "Шлем-тотем", "Потратить 1 чипсину, чтобы уничтожить карту?", [{"id":"yes","label":"Потратить 1 чипсину"},{"id":"no","label":"Не использовать"}], choose_use)


@effect("spell_vomitcan")
def vomitcan(game, player, card, **kw):
    if kw.get("attack_only", False):
        return
    if not player.deck:
        game.reshuffle_discard_into_deck(player)
    if not player.deck:
        return
    cid = player.deck.pop()
    revealed = game.cards[cid]
    def resolve(choice):
        if choice == "destroy":
            game.destroyed_pile.append(cid)
            return
        player.discard.append(cid)
        targets = [{"id":p.id,"label":p.name,"detail":f"Нанести {revealed.cost} урона"} for p in game.enemies_of(player)]
        def attack(target_id):
            game.deal_damage(player, target_id, revealed.cost, card.name)
        game.request_decision(player, "Пушка-блевушка", f"Выбери цель для {revealed.cost} урона.", targets, attack)
    game.request_decision(player, "Пушка-блевушка", f"Раскрыта «{revealed.name}» стоимостью {revealed.cost}.", [{"id":"destroy","label":"Уничтожить карту"},{"id":"attack","label":"Атаковать на её стоимость"}], resolve, revealed_cards=[_brief(game, cid)])
