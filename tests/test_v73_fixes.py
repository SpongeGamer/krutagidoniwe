"""Тесты правок v73: Бартоломяу, Шальная магия, выбор врага,
перенаправление атаки, показ уничтоженной карты."""
import pytest

from backend.game import GameState
from backend.effects import get_effect


def make_game(names=("A", "B"), seed=7):
    return GameState(list(names), seed=seed)


# --------------------------------------------------------------------------
# 1. Капитан Бартоломяу
# --------------------------------------------------------------------------

def test_captain_puts_chosen_card_into_play():
    """Выбранная карта попадает НА СТОЛ игрока и даёт мощь, а не сбрасывается."""
    game = make_game(seed=3)
    me, enemy = game.players
    power_card = next(cid for cid, c in game.cards.items()
                      if c.power == 3 and not c.has_attack)
    enemy.deck.extend(["start_znak", "start_znak", "start_znak", power_card])
    me.power_available = 0
    me.in_play_this_turn = []

    get_effect("leg_captain")(game, me, game.cards["leg_captain"],
                              use_attack=True, target_id=enemy.id)
    assert game.pending_decision, "Капитан обязан показать окно выбора"
    game.resolve_decision(me, power_card)

    assert power_card in me.in_play_this_turn, "карта должна лечь на стол игрока"
    assert me.power_available == 3, "мощь выбранной карты должна начислиться один раз"
    assert power_card not in enemy.discard, "выбранная карта не уходит в сброс сразу"
    assert len(enemy.discard) == 3, "остальные три карты уходят в сброс владельца"


def test_captain_returns_card_to_owner_at_end_of_turn():
    """«В этот ход считается, что ты контролируешь карту» — потом она уходит владельцу."""
    game = make_game(seed=4)
    me, enemy = game.players
    power_card = next(cid for cid, c in game.cards.items()
                      if c.power >= 2 and not c.has_attack)
    enemy.deck.extend(["start_znak", "start_znak", "start_znak", power_card])

    get_effect("leg_captain")(game, me, game.cards["leg_captain"],
                              use_attack=True, target_id=enemy.id)
    game.resolve_decision(me, power_card)
    game.end_turn(me)

    assert power_card in enemy.discard, "карта возвращается в сброс владельца"
    assert power_card not in me.discard, "карта не остаётся у того, кто её сыграл"


def test_captain_asks_target_for_attack_card():
    """Если выбранная карта — атакующая, игрок выбирает цель и урон проходит."""
    game = make_game(seed=5)
    me, enemy = game.players
    enemy.deck.extend(["start_znak", "start_znak", "start_znak", "start_syrpal"])
    enemy.hand = []
    hp_before = enemy.life

    get_effect("leg_captain")(game, me, game.cards["leg_captain"],
                              use_attack=True, target_id=enemy.id)
    game.resolve_decision(me, "start_syrpal")

    assert game.pending_decision, "у атакующей карты обязан быть выбор цели"
    game.resolve_decision(me, enemy.id)
    assert enemy.life < hp_before, "атака украденной карты должна нанести урон"


# --------------------------------------------------------------------------
# 2. Шальная магия
# --------------------------------------------------------------------------

def test_wild_magic_does_not_double_power():
    """Мощь украденной карты начисляется РОВНО один раз."""
    game = make_game(seed=1)
    me, enemy = game.players
    card_id = next(cid for cid, c in game.cards.items()
                   if c.power == 3 and not c.has_attack)
    enemy.deck.append(card_id)
    me.power_available = 0

    get_effect("spec_wild")(game, me, game.cards["spec_wild"],
                            choice="steal", target_id=enemy.id)
    assert me.power_available == 3, "было +6 из-за двойного начисления"


def test_wild_magic_plays_attack_fully():
    """Украденная карта с атакой разыгрывается полностью, а не только на мощь."""
    game = make_game(seed=2)
    me, enemy = game.players
    enemy.deck.append("start_syrpal")
    enemy.hand = []
    me.power_available = 0
    hp_before = enemy.life

    get_effect("spec_wild")(game, me, game.cards["spec_wild"],
                            choice="steal", target_id=enemy.id)
    assert me.power_available == 1, "мощь карты должна начислиться"
    assert game.pending_decision, "должен быть запрошен выбор цели для атаки"

    game.resolve_decision(me, enemy.id)
    assert enemy.life < hp_before, "атака украденной карты обязана сработать"


def test_wild_magic_borrowed_card_returns_to_owner():
    game = make_game(seed=6)
    me, enemy = game.players
    card_id = next(cid for cid, c in game.cards.items()
                   if c.power >= 1 and not c.has_attack and not c.postoyanka)
    enemy.deck.append(card_id)

    get_effect("spec_wild")(game, me, game.cards["spec_wild"],
                            choice="steal", target_id=enemy.id)
    game.end_turn(me)
    assert card_id in enemy.discard, "украденная карта возвращается владельцу"


# --------------------------------------------------------------------------
# 3. Выбор врага показывается всегда
# --------------------------------------------------------------------------

def test_leg_ass_asks_player_even_with_one_enemy():
    """«Восстание из зада» обязано показать окно выбора даже при одном враге."""
    game = make_game(seed=5)
    me, enemy = game.players

    get_effect("leg_ass")(game, me, game.cards["leg_ass"])
    assert game.pending_decision, "окно выбора врага должно открыться"
    assert enemy.no_defense_turn is False, "эффект не применяется до выбора"

    options = [o["id"] for o in game.pending_decision["options"]]
    assert enemy.id in options
    game.resolve_decision(me, enemy.id)
    assert enemy.no_defense_turn is True


def test_hostages_asks_player_for_target():
    """«Зожложники» тоже спрашивают, кто сбрасывает карту."""
    game = make_game(seed=8)
    me, enemy = game.players
    enemy.hand = ["start_znak", "start_znak"]

    get_effect("fam_hostages")(game, me, game.cards["fam_hostages"])
    assert game.pending_decision, "должно открыться окно выбора врага"
    game.resolve_decision(me, enemy.id)
    assert len(enemy.hand) == 1, "враг сбрасывает ровно одну карту"


# --------------------------------------------------------------------------
# 4. Перенаправление атаки
# --------------------------------------------------------------------------

def _defend_with(card_id, attacker_is_loshara=False, damage=5, seed=7):
    game = make_game(seed=seed)
    attacker, defender = game.players
    attacker.hand = []
    defender.hand = [card_id]
    if attacker_is_loshara:
        game.set_loshara(attacker, True)
    hp_attacker = attacker.life
    game.attack_target(attacker, game.cards["start_syrpal"], defender.id, damage)
    choice = next(o["id"] for o in game.pending_decision["options"]
                  if o["id"].startswith("defend:"))
    game.resolve_decision(defender, choice)
    return hp_attacker - attacker.life, game


@pytest.mark.parametrize("card_id", ["fam_benz", "fam_conduct", "fam_jester"])
def test_defense_redirects_attack_to_attacker(card_id):
    """Все карты с текстом «перенаправь атаку» возвращают урон атакующему."""
    redirected, _ = _defend_with(card_id)
    assert redirected == 5, f"{card_id} обязан перенаправить 5 урона"


def test_loshash_redirects_only_from_loshara():
    """Братья Лошашные разворачивают атаку ТОЛЬКО лошары."""
    normal, _ = _defend_with("leg_loshash", attacker_is_loshara=False)
    assert normal == 0, "обычный атакующий не должен получать урон"

    from_loshara, _ = _defend_with("leg_loshash", attacker_is_loshara=True)
    assert from_loshara == 5, "атака лошары обязана вернуться ему"


def test_no_redirect_flag_blocks_reflection():
    """Карту с пометкой «нельзя перенаправить» защита не разворачивает."""
    game = make_game(seed=9)
    attacker, defender = game.players
    attacker.hand = []
    defender.hand = ["fam_conduct"]
    hp_attacker = attacker.life

    game.attack_target(attacker, game.cards["leg_hahatalier"], defender.id, 5)
    assert game.pending_attack["no_redirect"] is True
    choice = next(o["id"] for o in game.pending_decision["options"]
                  if o["id"].startswith("defend:"))
    game.resolve_decision(defender, choice)
    assert attacker.life == hp_attacker, "эту атаку перенаправлять нельзя"


# --------------------------------------------------------------------------
# 5. Показ уничтоженной карты
# --------------------------------------------------------------------------

def test_mega5_announces_destroyed_card():
    """Мегабеспредел кладёт сгоревшую карту в ленту с картинкой и текстом."""
    game = make_game(seed=11)
    me = game.players[0]
    game.main_deck.append("start_znak")

    get_effect("mega_5")(game, me, game.cards["mega_5"])
    reel = game.to_public_dict(me.id)["destroy_reel"]
    assert reel, "лента уничтожений не должна быть пустой"
    entry = reel[0]
    assert entry["card_id"], "нужен id карты — по нему грузится картинка"
    assert entry["name"], "нужно название"
    assert entry["reason"], "нужно объяснение, почему карта сгорела"
    assert entry["victim"], "нужно имя того, кто потерял карту"


def test_destroy_from_zone_announces_card():
    game = make_game(seed=12)
    me = game.players[0]
    me.hand = ["start_znak"]

    game.destroy_from_zone(me, "start_znak", "hand")
    reel = game.to_public_dict(me.id)["destroy_reel"]
    assert reel and reel[-1]["card_id"] == "start_znak"


def test_destroy_reel_keeps_sequence_growing():
    """У каждой сгоревшей карты свой seq — иначе клиент пропустит анимацию."""
    game = make_game(seed=13)
    me = game.players[0]
    me.hand = ["start_znak", "start_znak"]
    game.destroy_from_zone(me, "start_znak", "hand")
    game.destroy_from_zone(me, "start_znak", "hand")
    seqs = [d["seq"] for d in game.destroy_reel]
    assert seqs == sorted(set(seqs)), "seq должен строго расти"


def test_logs_keep_100_lines():
    """Журнал держит 100 строк: цепочка Беспределов вытесняла всё за 30."""
    game = make_game(seed=14)
    for i in range(150):
        game.log(f"строка {i}")
    logs = game.to_public_dict(game.players[0].id)["logs"]
    assert len(logs) == 100
