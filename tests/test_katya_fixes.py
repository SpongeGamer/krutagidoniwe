"""Регрессии по 14 багам, найденным в трёх живых партиях."""
import pytest
from backend.game import GameState


def new_game(names=("A", "B", "C"), seed=5):
    g = GameState(list(names), seed=seed)
    g.turn_idx = 0
    return g


# --- #1: самоурон ---------------------------------------------------------
def test_attack_never_hits_self():
    g = new_game()
    me = g.players[0]
    before = me.life
    g.attack_target(me, g.cards["wiz_sosok"], me.id, 7)
    assert me.life == before
    assert g.pending_attack is None


def test_variable_attack_drops_self_but_keeps_enemies():
    """Урон уходит врагу, а часть, направленная на себя, отбрасывается."""
    g = new_game()
    me, foe = g.players[0], g.players[1]
    my_hp, foe_hp = me.life, foe.life
    g.declare_variable_attack(me, g.cards["wiz_sosok"], [(me, 5), (foe, 5)])
    assert me.life == my_hp, "по себе урона быть не должно"
    assert foe.life == foe_hp - 5


# --- #3: главный приз -----------------------------------------------------
def test_prize_goes_to_first_killer_when_nobody_owns_it():
    g = new_game()
    killer, victim = g.players[0], g.players[1]
    g.undead_token_stack = []
    assert g.prize_holder is None
    g._handle_death(victim, killer)
    assert g.prize_holder == killer.id and killer.controls_prize


def test_prize_stays_when_a_third_player_dies():
    g = new_game()
    owner, victim, killer = g.players
    owner.controls_prize = True
    g.prize_holder = owner.id
    g.undead_token_stack = []
    g._handle_death(victim, killer)
    assert g.prize_holder == owner.id


def test_prize_moves_from_owner_to_killer():
    g = new_game()
    owner, killer = g.players[0], g.players[1]
    owner.controls_prize = True
    g.prize_holder = owner.id
    g.undead_token_stack = []
    g._handle_death(owner, killer)
    assert g.prize_holder == killer.id


# --- #4/#5: защита и описание атаки --------------------------------------
def test_vomitcan_attack_is_defendable():
    g = new_game(("A", "B"), seed=11)
    me, foe = g.players
    foe.hand = ["fam_hostages"]
    me.deck.append("leg_minigun")
    me.hand.append("spell_vomitcan")
    g.play_card(me, "spell_vomitcan")
    g.resolve_decision(me, "attack")
    g.resolve_decision(me, foe.id)
    d = g.pending_decision
    assert d["player_name"] == foe.name
    assert any(str(o["id"]).startswith("defend") for o in d["options"])


def test_defense_window_explains_the_attack():
    g = new_game(("A", "B"), seed=11)
    me, foe = g.players
    foe.hand = ["fam_hostages"]
    g.attack_target(me, g.cards["leg_hemor"], foe.id, 3)
    text = g.pending_decision["text"]
    assert "Что делает карта" in text and "вялые палочки" in text.lower()
    assert g.pending_decision["revealed_cards"]


# --- #6: миниган ----------------------------------------------------------
def test_minigun_asks_for_a_target():
    g = new_game()
    assert g.card_needs_target(g.cards["leg_minigun"]) is False
    me = g.players[0]
    me.hand.append("leg_minigun")
    g.play_card(me, "leg_minigun")
    assert g.pending_decision is not None
    assert "Выстрел 1" in g.pending_decision["text"]


def test_minigun_single_enemy_fires_all_four_shots():
    """Один враг — окно выбора не нужно, но все 4 выстрела по 7 доходят."""
    g = new_game(("A", "B"), seed=5)
    me, foe = g.players
    foe.life = foe.max_life = 100
    me.hand.append("leg_minigun")
    g.play_card(me, "leg_minigun")
    assert g.pending_decision is None
    assert foe.life == 100 - 28


# --- #7: дохляки ----------------------------------------------------------
def test_dohlyak_pays_every_turn():
    g = new_game(("A", "B"), seed=5)
    me = g.players[0]
    me.death_tokens = ["dk_1", "dk_2"]
    me.hand.append("sdk_1")
    g.play_card(me, "sdk_1")
    on_play = me.chipsines
    assert on_play == 3
    g.end_turn(me)
    assert me.chipsines == on_play + 3


# --- #8/#10: защиты фамильяров -------------------------------------------
def test_hostages_counterattack():
    g = new_game(("A", "B"), seed=11)
    me, foe = g.players
    foe.hand = ["fam_hostages"]
    before = me.life
    g.attack_target(me, g.cards["wiz_sosok"], foe.id, 7)
    opt = [o["id"] for o in g.pending_decision["options"]
           if str(o["id"]).startswith("defend")][0]
    g.resolve_decision(foe, opt)
    assert before - me.life == 6


def test_mescalito_offers_token_swap():
    g = new_game(("A", "B"), seed=3)
    me, foe = g.players
    foe.hand = ["fam_mescalito"]
    me.death_tokens = ["dk_1"]
    foe.death_tokens = ["dk_1"]
    g.attack_target(me, g.cards["wiz_sosok"], foe.id, 5)
    opt = [o["id"] for o in g.pending_decision["options"]
           if str(o["id"]).startswith("defend")][0]
    g.resolve_decision(foe, opt)
    assert g.pending_decision["title"].startswith("Мескалито")
    assert "dk_1" in [o["id"] for o in g.pending_decision["options"]]


# --- #9: очередь решений --------------------------------------------------
def test_nested_decisions_are_queued_not_lost():
    g = new_game(("A", "B"), seed=3)
    me = g.players[0]
    seen = []
    g.request_decision(me, "ПЕРВЫЙ", "1", [{"id": "a", "label": "A"}], lambda c: seen.append("1" + c))
    g.request_decision(me, "ВТОРОЙ", "2", [{"id": "b", "label": "B"}], lambda c: seen.append("2" + c))
    assert g.pending_decision["title"] == "ПЕРВЫЙ"
    g.resolve_decision(me, "a")
    assert g.pending_decision["title"] == "ВТОРОЙ"
    g.resolve_decision(me, "b")
    assert seen == ["1a", "2b"]
    assert g.pending_decision is None


# --- #12: беспредел закрывает каждый сам ---------------------------------
def test_event_waits_for_every_player():
    g = new_game()
    a, b, c = g.players
    g._queue_event(g.cards["besp_1"])
    assert g.pending_event is not None
    g.resolve_event(a)
    assert g.pending_event is not None, "окно не должно закрываться после первого игрока"
    g.resolve_event(b)
    assert g.pending_event is not None
    g.resolve_event(c)
    assert g.pending_event is None or g.pending_event.get("name") != "besp_1"


def test_event_state_reports_who_is_still_reading():
    g = new_game()
    a = g.players[0]
    g._queue_event(g.cards["besp_1"])
    g.resolve_event(a)
    state = g.to_public_dict(a.id)
    assert state["pending_event"]["seen"] is True
    assert a.name not in state["pending_event"]["waiting_names"]
    assert len(state["pending_event"]["waiting_names"]) == 2


# --- #11: плашка ожидания ------------------------------------------------
def test_other_players_see_what_is_awaited():
    g = new_game(("A", "B"), seed=11)
    me, foe = g.players
    foe.hand = ["fam_hostages"]
    g.attack_target(me, g.cards["wiz_sosok"], foe.id, 7)
    state = g.to_public_dict(me.id)
    assert state["pending_decision"]["waiting_for"] == foe.name
    assert state["pending_decision"]["waiting_title"]
