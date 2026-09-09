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
def test_dohlyak_pays_once_on_play_only():
    """Выплата РАЗОВАЯ: «сыграв эту карту, получи 1 чипсину за каждый жетон».

    Ежеходное начисление — ошибка: оно давало боту десятки чипсин из воздуха.
    """
    g = new_game(("A", "B"), seed=5)
    me = g.players[0]
    me.death_tokens = ["dk_1", "dk_2"]
    me.hand.append("sdk_1")
    g.play_card(me, "sdk_1")
    on_play = me.chipsines
    assert on_play == 3          # 2 жетона + сама карта
    g.end_turn(me)
    assert me.chipsines == on_play, "Дохляк не должен доплачивать в конце хода"


def test_dohlyaki_do_not_snowball():
    """Три Дохляка + Постояночка: никакого роста в холостые ходы."""
    g = new_game(("A", "B"), seed=7)
    me = g.players[0]
    me.property_id = "svo_5"
    me.death_tokens = ["dk_18", "dk_3"]
    for cid in ("sdk_1", "sdk_2", "sdk_3"):
        me.hand.append(cid)
        g.play_card(me, cid)
    frozen = me.chipsines
    for _ in range(5):
        g.end_turn(me)
        g.turn_idx = 0
    assert me.chipsines == frozen


def test_each_dohlyak_counts_as_a_token_for_the_next():
    """Постоянка означает: карта сама считается жетоном ЖДК."""
    g = new_game(("A", "B"), seed=7)
    me = g.players[0]
    me.death_tokens = ["dk_18"]
    me.hand += ["sdk_1", "sdk_2"]
    g.play_card(me, "sdk_1")
    first = me.chipsines
    assert first == 2            # 1 жетон + сама карта
    g.play_card(me, "sdk_2")
    assert me.chipsines - first == 3   # 1 жетон + лежащий Дохляк + сама карта


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


# --- добор карт по тексту (жалоба на Никчемухажёров и Бесопанков) ---------
def _defend_with(cid, seed=11, loshara=False):
    g = new_game(("A", "B"), seed=seed)
    a, b = g.players
    if loshara:
        g.set_loshara(a)
    b.hand = [cid, "start_znak", "start_znak", "start_pshik"]
    b.deck = ["leg_rabbit"] * 8
    before_deck = len(b.deck)
    hp_attacker = a.life
    g.attack_target(a, g.cards["wiz_sosok"], b.id, 7)
    opt = [o["id"] for o in g.pending_decision["options"]
           if str(o["id"]).startswith("defend")][0]
    g.resolve_decision(b, opt)
    return g, a, b, before_deck - len(b.deck), hp_attacker - a.life


def test_punks_draw_and_deal_three():
    """Бесопанки: +1 карта и 3 урона (в коде стояло 2)."""
    g, a, b, drawn, dmg = _defend_with("wiz_punks")
    assert drawn == 1
    assert dmg == 3


def test_suitors_are_revealed_not_discarded():
    """Никчемухажёры раскрываются и ОСТАЮТСЯ на руке, сбрасывается другая."""
    g, a, b, drawn, dmg = _defend_with("fam_suitors")
    assert "fam_suitors" in b.hand, "карта должна остаться на руке"
    assert drawn == 0, "текст защиты не обещает добора"
    assert len(b.discard) == 1 and b.discard[0] != "fam_suitors"
    assert b.life == 20, "атака всё равно должна быть отражена"


def test_legend_keeper_defense_full_payout():
    """Легендохранитель: 2 карты И 2 чипсины (было 1 карта, 0 чипсин)."""
    g, a, b, drawn, dmg = _defend_with("leg_legdef")
    assert drawn == 2
    assert b.chipsines == 2


# --- Мортал Комбо: плашка только после выбора -----------------------------
def test_mortal_shows_token_only_after_killer_picks():
    g = new_game(("Убийца", "Жертва"), seed=4)
    killer, victim = g.players
    victim.life = 5
    victim.hand = []
    killer.hand.append("leg_mortal")
    g.play_card(killer, "leg_mortal", target_id=victim.id)

    assert g.pending_event is None, "плашка не должна всплывать до выбора"
    assert victim.death_tokens == [], "жетон выдаётся только после выбора"

    d = g.pending_decision
    assert d and d["title"] == "Мортал Комбо"
    assert len(d["options"]) == 3

    chosen = d["options"][1]
    g.resolve_decision(killer, chosen["id"])

    assert g.pending_event is not None
    assert g.pending_event["name"] == chosen["label"], "показан именно выбранный жетон"
    assert g.pending_event["owner"] == victim.name
    assert len(victim.death_tokens) == 1


# --- сверка с ОРИГИНАЛАМИ карт (фото прислал пользователь) ----------------
def test_punks_draw_on_play_and_have_no_power():
    """Бесопанки: «Возьми 1 карту», бонуса мощи у карты НЕТ.

    В базе ошибочно стояло «+2 мощи», а верхняя строка «Возьми 1 карту»
    вообще отсутствовала — эффект был заглушкой `pass`.
    """
    g = new_game(("A", "B"), seed=11)
    me = g.players[0]
    me.hand = ["wiz_punks"]
    me.deck = ["start_znak"] * 6
    me.power_available = 0
    before = len(me.deck)
    g.play_card(me, "wiz_punks")
    assert before - len(me.deck) == 1, "должна добираться 1 карта"
    assert me.power_available == 0, "мощи карта не даёт"


def test_punks_card_text_matches_the_printed_card():
    g = new_game()
    text = g.cards["wiz_punks"].full_text
    assert text.startswith("Возьми 1 карту.")
    assert "+2 мощи" not in text
    assert g.cards["wiz_punks"].power == 0


def test_suitors_draw_on_play_and_give_two_power():
    """Никчемухажёры: +2 мощи и «Возьми 1 карту» при розыгрыше."""
    g = new_game(("A", "B"), seed=11)
    me = g.players[0]
    me.hand = ["fam_suitors"]
    me.deck = ["start_znak"] * 6
    me.power_available = 0
    before = len(me.deck)
    g.play_card(me, "fam_suitors")
    assert before - len(me.deck) == 1
    assert me.power_available == 2


# --- «за каждый жетон ЖДК»: Дохляки тоже считаются -----------------------
def test_zhdk_count_includes_dohlyaki():
    """Дохляк на столе САМ считается жетоном дохлого колдуна."""
    g = new_game(("A", "B"), seed=11)
    me = g.players[0]
    me.death_tokens = ["dk_1", "dk_2"]
    me.zone_in_play = ["sdk_1", "sdk_2"]
    assert g.zhdk_count(me) == 4


def test_necrostrip_counts_dohlyaki():
    """Некрошест: +2 мощи за каждый ЖДК, включая Дохляков на столе."""
    g = new_game(("A", "B"), seed=11)
    me = g.players[0]
    me.death_tokens = ["dk_1"]
    me.zone_in_play = ["sdk_1"]
    me.hand = ["treas_necrostrip"]
    me.power_available = 0
    g.play_card(me, "treas_necrostrip")
    assert me.power_available == 4      # (1 жетон + 1 Дохляк) * 2


def test_necrorot_counts_dohlyaki():
    """Гнилюся: 4 урона каждому врагу за каждый ЖДК, Дохляки в счёт."""
    g = new_game(("A", "B"), seed=11)
    me, foe = g.players
    me.death_tokens = ["dk_1"]
    me.zone_in_play = ["sdk_1", "sdk_2"]
    foe.life = foe.max_life = 100
    me.hand = ["leg_necrorot"]
    g.play_card(me, "leg_necrorot")
    assert 100 - foe.life == 12         # (1 + 2) * 4


def test_orangutan_counts_itself():
    """Трахангутан: +3 мощи за каждую тварь, включая себя самого."""
    g = new_game(("A", "B"), seed=11)
    me = g.players[0]
    me.zone_in_play = ["beast_kinky"]
    me.hand = ["beast_orangutan"]
    me.power_available = 0
    g.play_card(me, "beast_orangutan")
    assert me.power_available == 6      # своя тварь + одна на столе


def test_orangutan_alone_gives_three():
    g = new_game(("A", "B"), seed=11)
    me = g.players[0]
    me.zone_in_play = []
    me.hand = ["beast_orangutan"]
    me.power_available = 0
    g.play_card(me, "beast_orangutan")
    assert me.power_available == 3
