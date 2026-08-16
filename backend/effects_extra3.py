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
        target.is_loshara = True
        target.max_life = 15
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
