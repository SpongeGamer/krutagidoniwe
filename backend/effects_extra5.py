"""Эффекты с приватным раскрытием карт."""
from .effects import effect, activation


def brief(game, cid):
    c = game.cards[cid]
    return {"id": c.id, "name": c.name, "type": c.type, "cost": c.cost, "power": c.power, "vp": c.vp,
            "has_attack": c.has_attack, "text": c.full_text}


@effect("wiz_surok")
def surok(game, player, card, **kw):
    if kw.get("attack_only", False):
        return
    revealed = []
    for _ in range(3):
        if not game.main_deck:
            break
        cid = game.main_deck.pop()
        revealed.append(cid)
        game.destroyed_pile.append(cid)
    if not revealed:
        return
    besps = [cid for cid in revealed if game.cards[cid].type == "Беспредел"]
    options = [{"id": "skip", "label": "Не играть Беспредел", "detail": "+3 мощи не получаю"}]
    options += [{"id": cid, "label": f"Сыграть «{game.cards[cid].name}»", "detail": "+3 мощи"} for cid in besps]
    def choose(choice):
        if choice in besps:
            player.power_available += 3
            # Беспредел показывается всем отдельным событием, а не разыгрывается молча.
            game._queue_event(game.cards[choice])
            game.log(f"{player.name}: Сурковый агент играет найденный Беспредел")
    game.request_decision(
        player,
        "Сурковый агент",
        "Уничтожены 3 верхние карты основной колоды. Если среди них Беспредел — можешь сыграть один и получить +3 мощи.",
        options,
        choose,
        revealed_cards=[brief(game, cid) for cid in revealed],
    )

@activation("wiz_marmemage")
def activate_marmemage(game, player, card, **kw):
    game.destroy_from_zone(player, card.id, "zone_in_play")
    if player.is_loshara:
        game.set_loshara(player, False)
    game.heal(player, 7)
    game.log(f"{player.name}: активирует Мармеладного архимага")


@activation("beast_jaba")
def activate_jaba(game, player, card, **kw):
    target_id = kw.get("target_id")
    if not target_id:
        # Фронтенд открывает обычный выбор цели до отправки активации.
        return
    game.destroy_from_zone(player, card.id, "zone_in_play")
    def make_loshara(target, dead):
        game.set_loshara(target, True)
    game.attack_target(player, card, target_id, 0, on_hit=make_loshara)


@activation("spell_magicspill")
def activate_magicspill(game, player, card, **kw):
    target_id = kw.get("target_id")
    if not target_id:
        return
    target = game.get_player(target_id)
    if not target:
        return
    game.destroy_from_zone(player, card.id, "zone_in_play")
    def choose_cards(hit_target, dead):
        def choose_again(left):
            if left <= 0 or not hit_target.hand:
                return
            options = [{"id":"finish","label":"Закончить уничтожение"}] + [
                {"id":cid,"label":game.cards[cid].name,"detail":"Карта на руке цели"}
                for cid in hit_target.hand
            ]
            def resolve(choice):
                if choice != "finish" and choice in hit_target.hand:
                    hit_target.hand.remove(choice)
                    game.destroyed_pile.append(choice)
                    choose_again(left-1)
            game.request_decision(player, "Волшебные отходы", "Уничтожь до двух карт с руки атакованного колдуна.", options, resolve)
        choose_again(2)
    game.attack_target(player, card, target_id, 0, on_hit=choose_cards)
