"""Пакет базовых эффектов основной колоды.
Импортируется из effects.py, чтобы реестр оставался компактным по разделам.
"""
from .effects import effect


@effect("beast_orangutan")
def orangutan(game, player, card, **kw):
    player.power_available += 3 * game.count_controlled_type(player, "Тварь")


@effect("beast_kinky")
def kinky(game, player, card, **kw):
    if kw.get("use_attack", True):
        game.declare_attack(player, card, "all_enemies", 3 * game.count_controlled_type(player, "Тварь"))


@effect("beast_spanish")
def spanish(game, player, card, **kw):
    if kw.get("use_attack", True) and game.count_controlled_type(player, "Тварь", card.id) >= 1:
        game.attack_target(player, card, kw.get("target_id"), 9)


@effect("beast_peyot")
def peyot(game, player, card, **kw):
    if game.count_controlled_type(player, "Тварь", card.id) >= 1:
        player.chipsines += 1


@effect("spell_lohbbq")
def lohbbq(game, player, card, **kw):
    player.chipsines += sum(p.is_loshara for p in game.players)


@effect("wiz_bandits")
def bandits(game, player, card, **kw):
    if kw.get("use_attack", True): game.declare_attack(player, card, "all_enemies", 3)


@effect("wiz_sheriff")
def sheriff(game, player, card, **kw):
    if not kw.get("attack_only", False): game.draw_cards(player, 2)


@effect("wiz_smurf")
def smurf(game, player, card, **kw):
    if kw.get("use_attack", True):
        game.attack_target(player, card, kw.get("target_id"), 4, on_hit=lambda target, died: game.heal(player, 4))


@effect("wiz_sosok")
def sosok(game, player, card, **kw):
    if kw.get("use_attack", True): game.declare_attack(player, card, "all_enemies", 7)


@effect("wiz_blacksheep")
def blacksheep(game, player, card, **kw):
    if not kw.get("use_attack", True): return
    target = game.get_player(kw.get("target_id"))
    if target and game.legend_deck:
        cid = game.legend_deck.pop(); destroyed = game.cards[cid]
        game.destroyed_pile.append(cid)
        game.attack_target(player, card, target.id, destroyed.cost)


@effect("wiz_peel")
def peel(game, player, card, **kw):
    if not kw.get("use_attack", True) or game.vyal_remaining <= 0: return
    target=game.get_player(kw.get("target_id"))
    if target:
        def give_stick(hit_target, died):
            hit_target.hand.append("spec_vyal")
            game.vyal_remaining -= 1
        game.attack_target(player, card, target.id, 0, on_hit=give_stick)


@effect("spell_wolfhunger")
def wolfhunger(game, player, card, **kw):
    if not kw.get("use_attack", True): return
    target=game.get_player(kw.get("target_id"))
    if target:
        def discard_random(hit_target, died):
            if hit_target.hand:
                hit_target.discard.append(hit_target.hand.pop(game.rng.randrange(len(hit_target.hand))))
        game.attack_target(player, card, target.id, 4, on_hit=discard_random)


@effect("spell_donate")
def donate(game, player, card, **kw):
    if not kw.get("use_attack", True): return
    costs=[game.cards[cid].cost for cid in game.controlled_card_ids(player) if cid != card.id]
    if costs: game.attack_target(player, card, kw.get("target_id"), max(costs))


@effect("treas_necrostrip")
def necrostrip(game, player, card, **kw):
    player.power_available += 2 * len(player.death_tokens)


@effect("treas_vordal")
def vordal(game, player, card, **kw):
    if len(player.in_play_this_turn)==1:
        player.discard.extend(player.hand); player.hand=[]; game.draw_cards(player,4)


@effect("treas_epicmerch")
def epicmerch(game, player, card, **kw):
    player.legend_discount_turn=getattr(player,"legend_discount_turn",0)+2


@effect("treas_losharochka")
def losharochka(game, player, card, **kw):
    if not kw.get("use_attack", True): return
    target=game.get_player(kw.get("target_id"))
    if target:
        def make_loshara(hit_target, died):
            if died:
                hit_target.is_loshara = True
                hit_target.max_life = 15
        game.attack_target(player, card, target.id, 5, on_hit=make_loshara)


@effect("treas_shlepal")
def shlepal(game, player, card, **kw):
    if not kw.get("use_attack", True): return
    target=game.get_player(kw.get("target_id"))
    if target:
        def steal_chips(hit_target, died):
            hit_target.chipsines = max(0, hit_target.chipsines - 2)
            player.chipsines += 2
        game.attack_target(player, card, target.id, 2, on_hit=steal_chips)
