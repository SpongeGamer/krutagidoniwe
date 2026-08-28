"""Пакет прямых эффектов легенд: добор, мощь и атаки без сложного выбора зон."""
from .effects import effect


@effect("leg_orbital")
def orbital(game, player, card, **kw):
    if kw.get("use_attack", True):
        game.declare_attack(player, card, "left_right", 10)


@effect("leg_loxolox")
def loxolox(game, player, card, **kw):
    if not kw.get("attack_only", False):
        player.power_available *= 2


@effect("leg_rabbit")
def rabbit(game, player, card, **kw):
    if not kw.get("attack_only", False):
        game.draw_cards(player, 3)
    if kw.get("use_attack", True):
        game.declare_attack(player, card, "all_enemies", 20)


@effect("leg_legdef")
def legdef(game, player, card, **kw):
    if not kw.get("attack_only", False):
        game.draw_cards(player, 2)
        player.chipsines += 2


@effect("leg_necrorot")
def necrorot(game, player, card, **kw):
    if kw.get("use_attack", True):
        game.declare_attack(player, card, "all_enemies", 4 * len(player.death_tokens))


@effect("leg_avada")
def avada(game, player, card, **kw):
    if not kw.get("attack_only", False):
        game.draw_cards(player, 2)
    if not kw.get("use_attack", True):
        return
    def make_loshara(target, died):
        game.set_loshara(target, True)
        player.power_available += sum(p.is_loshara for p in game.players)
    game.attack_target(player, card, kw.get("target_id"), 0, on_hit=make_loshara)


@effect("leg_hemor")
def hemor(game, player, card, **kw):
    if not kw.get("use_attack", True):
        return
    def give_sticks(target, died):
        game.give_weak_sticks(target, 2, "hand")
    game.declare_attack(player, card, "all_enemies", 0, on_hit=give_sticks)


@effect("leg_backinass")
def backinass(game, player, card, **kw):
    player.market_to_hand_turn = True


@effect("leg_shitcher")
def shitcher(game, player, card, **kw):
    if not game.legend_market:
        return
    cid = game.rng.choice(game.legend_market)
    game.legend_market.remove(cid)
    destroyed = game.cards[cid]
    game.destroyed_pile.append(cid)
    if kw.get("use_attack", True):
        game.declare_attack(player, card, "all_enemies", destroyed.cost)


@effect("leg_holest")
def holest(game, player, card, **kw):
    if not player.death_tokens:
        player.power_available += 7
        return
    options = [{"id":"keep", "label":"Не уничтожать жетон"}] + [
        {"id":tid, "label":game.zhdk.get(tid,{}).get("name",tid)} for tid in player.death_tokens
    ]
    def choose(choice):
        if choice in player.death_tokens:
            player.death_tokens.remove(choice)
            game.log(f"{player.name}: уничтожает свой жетон ЖДК")
    game.request_decision(player,"Смерть от холестерина","Можешь уничтожить один свой жетон дохлого колдуна.",options,choose)

@effect("leg_rlyeh")
def rlyeh(game, player, card, **kw):
    if kw.get("attack_only", False):
        return
    for target in game.players:
        game.draw_cards(target, 2)
    # Неизбежная атака: случайно сбросить две карты и получить сумму их стоимостей.
    for target in game.enemies_of(player):
        dropped=[]
        for _ in range(2):
            if target.hand:
                cid=target.hand.pop(game.rng.randrange(len(target.hand)))
                target.discard.append(cid); dropped.append(cid)
        damage=sum(game.cards[cid].cost for cid in dropped)
        game.deal_damage(player,target.id,damage,card.name,defendable=False,unavoidable=True)


@effect("leg_ass")
def ass(game, player, card, **kw):
    if not kw.get("attack_only", False):
        game.draw_cards(player,2)
    target=game.get_player(kw.get("target_id"))
    if target:
        target.no_defense_turn=True
        game.log(f"{target.name}: не может защищаться до конца хода")


@effect("leg_hahatalier")
def hahatalier(game, player, card, **kw):
    if not kw.get("use_attack",True): return
    target=game.get_player(kw.get("target_id"))
    if not target: return
    for _ in range(min(2,len(game.undead_token_stack))):
        target.death_tokens.append(game.undead_token_stack.pop())


@effect("leg_palush")
def palush(game, player, card, **kw):
    if not kw.get("use_attack",True): return
    target=game.get_player(kw.get("target_id"))
    def win_on_kill(hit_target,died):
        if died:
            game.game_over=True
            game.winner=player.id
            game.log(f"{player.name}: Палочка-ушаталочка приносит мгновенную победу!")
    if target: game.attack_target(player,card,target.id,1,on_hit=win_on_kill)

@effect("leg_soton")
def soton(game, player, card, **kw):
    """Уничтожение любого количества карт сброса: выбор повторяется, пока игрок не откажется."""
    def choose_again():
        options = [{"id":"finish","label":"Закончить уничтожение"}] + [
            {"id":cid,"label":game.cards[cid].name,"detail":f"Стоимость {game.cards[cid].cost}"}
            for cid in player.discard
        ]
        def resolve(choice):
            if choice != "finish" and choice in player.discard:
                game.destroy_from_zone(player, choice, "discard")
                choose_again()
        game.request_decision(player, "Сделка с Сотоной", "Уничтожь любое количество карт в своём сбросе.", options, resolve)
    choose_again()


@effect("leg_plan")
def plan(game, player, card, **kw):
    if kw.get("attack_only", False):
        return
    game.draw_cards(player, 2)
    if len(game.controlled_card_ids(player)) < 11 or not game.legend_deck:
        return
    revealed = []
    for _ in range(min(5, len(game.legend_deck))):
        revealed.append(game.legend_deck.pop())
    options = [{"id": cid, "label": game.cards[cid].name, "detail": f"Стоимость {game.cards[cid].cost}"} for cid in revealed]
    def choose(choice):
        if choice in revealed:
            player.deck.append(choice)
            revealed.remove(choice)
        # Остальные возвращаются наверх легендарной колоды; произвольный порядок пока исходный.
        game.legend_deck.extend(reversed(revealed))
    game.request_decision(player, "Надёжный план", "Выбери одну из пяти легенд и положи на верх своей колоды.", options, choose)
