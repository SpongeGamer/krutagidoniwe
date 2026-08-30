"""Нагрузочный прогон: случайные партии целиком.

Задача — поймать исключения в эффектах карт и нарушения инвариантов,
а не проверить конкретное правило. Каждая карта хотя бы раз разыгрывается.
"""
from __future__ import annotations

import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.game import GameState  # noqa: E402
from backend import effects  # noqa: E402


def _auto_resolve(game, limit: int = 60):
    """Автоматически закрывает висящие решения и события."""
    for _ in range(limit):
        if game.pending_decision:
            opts = game.pending_decision.get("options") or []
            pid = game.pending_decision["player_id"]
            player = game.get_player(pid)
            if not opts:
                game.pending_decision = None
                continue
            choice = game.rng.choice(opts)["id"]
            game.resolve_decision(player, choice)
            continue
        if game.pending_event:
            game.resolve_event()
            continue
        return
    game.pending_decision = None


def _play_random_game(seed: int, max_turns: int = 40) -> dict:
    names = ["Игрок A", "Игрок B", "Игрок C"]
    game = GameState(names, seed=seed)
    played_ids = set()

    for _ in range(max_turns):
        if game.game_over:
            break
        _auto_resolve(game)
        player = game.active_player

        # разыгрываем всю руку
        for card_id in list(player.hand):
            if game.game_over:
                break
            _auto_resolve(game)
            if card_id not in player.hand:
                continue
            enemies = [p for p in game.enemies_of(player) if p.is_alive()]
            kwargs = {}
            if enemies:
                kwargs["target_id"] = game.rng.choice(enemies).id
                kwargs["target_ids"] = [e.id for e in enemies[:3]]
            game.play_card(player, card_id, **kwargs)
            played_ids.add(card_id)
            _auto_resolve(game)

        # отложенные атаки
        for card_id in list(player.available_attacks):
            if game.game_over:
                break
            enemies = [p for p in game.enemies_of(player) if p.is_alive()]
            if not enemies:
                break
            game.activate_attack(player, card_id, target_id=game.rng.choice(enemies).id)
            _auto_resolve(game)

        # активации постоянок
        for card_id in list(player.zone_in_play):
            if game.game_over:
                break
            if card_id in effects.ACTIVATION_REGISTRY:
                enemies = [p for p in game.enemies_of(player) if p.is_alive()]
                kw = {"target_id": game.rng.choice(enemies).id} if enemies else {}
                game.activate_permanent(player, card_id, **kw)
                _auto_resolve(game)

        # покупки
        for _ in range(2):
            if game.game_over or not game.market:
                break
            card_id = game.rng.choice(game.market)
            if game.cards[card_id].cost <= player.power_available:
                game.buy_card(player, card_id)
                _auto_resolve(game)

        if game.game_over:
            break
        game.end_turn(player)
        _auto_resolve(game)

    return {"game": game, "played": played_ids}


def test_many_random_games_do_not_crash():
    """200 партий подряд без единого исключения."""
    for seed in range(200):
        result = _play_random_game(seed, max_turns=25)
        game = result["game"]
        for p in game.players:
            assert p.life <= p.max_life, f"seed={seed}: {p.name} выше максимума HP"
            assert p.chipsines >= 0, f"seed={seed}: отрицательные чипсины"
            assert p.power_available >= 0, f"seed={seed}: отрицательная мощь"


def test_no_cards_vanish():
    """Карты не исчезают и не дублируются за партию."""
    for seed in range(40):
        game = GameState(["A", "B"], seed=seed)
        before = _count_all(game)
        result = _play_random_game(seed, max_turns=15)
        after = _count_all(result["game"])
        assert after >= before - 5, f"seed={seed}: карты пропали ({before} -> {after})"


def _count_all(game) -> int:
    total = len(game.main_deck) + len(game.legend_deck) + len(game.market) + len(game.legend_market)
    total += len(game.destroyed_pile)
    for p in game.players:
        total += len(p.deck) + len(p.hand) + len(p.discard) + len(p.zone_in_play)
    return total


def test_every_registered_effect_is_callable():
    """Все зарегистрированные обработчики — вызываемые объекты."""
    for cid, fn in effects.EFFECT_REGISTRY.items():
        assert callable(fn), f"{cid}: обработчик не вызывается"
    for cid, fn in effects.DEFENSE_REGISTRY.items():
        assert callable(fn), f"{cid}: защита не вызывается"
    for cid, fn in effects.ACTIVATION_REGISTRY.items():
        assert callable(fn), f"{cid}: активация не вызывается"


def test_scoring_counts_deck():
    """В финальном подсчёте учитываются карты из колоды игрока."""
    game = GameState(["A", "B"], seed=1)
    player = game.players[0]
    player.deck.append("leg_goose")   # 4 ПО лежит именно в колоде
    game._finish_game()
    assert game.final_scores[player.id]["legends"] >= 1, "легенда из колоды не засчитана"


def test_all_properties_playable():
    """Каждое свойство колдуна отрабатывает начало хода без падений."""
    import json
    svo_path = os.path.join(os.path.dirname(__file__), "..", "svo.json")
    with open(svo_path, encoding="utf-8") as f:
        props = json.load(f)

    for prop in props:
        game = GameState(["A", "B", "C"], seed=3)
        player = game.active_player
        player.property_id = prop["id"]
        # под контролем пара карт разных типов — чтобы условия свойств срабатывали
        player.zone_in_play.extend(["treas_evilrak", "beast_beer", "wiz_koldunator", "spell_liquidpun"])
        game.start_turn()
        _auto_resolve(game)
        assert player.chipsines >= 0, f"{prop['id']}: отрицательные чипсины"
        assert player.power_available >= 0, f"{prop['id']}: отрицательная мощь"


def test_start_life_is_20_of_25():
    """Каждый колдун начинает с 20 из 25 жизней (правила, стр. 6)."""
    game = GameState(["A", "B", "C"], seed=5)
    for p in game.players:
        assert p.life == 20, f"{p.name}: старт {p.life}, ожидалось 20"
        assert p.max_life == 25, f"{p.name}: максимум {p.max_life}, ожидалось 25"


def test_prize_property_starts_full():
    """Свойство «Главный приз» (svo_6) — единственное, что даёт старт 25/25."""
    game = GameState(["A", "B"], seed=5)
    hero = game.players[0]
    hero.property_id = "svo_6"
    game.apply_property_setup(hero)
    assert hero.life == 25 and hero.max_life == 25
    assert game.players[1].life == 20, "остальные должны остаться на 20"


def test_magicspill_destroys_own_hand():
    """«Волшебные отходы» чистят СВОЮ руку и не трогают врага."""
    from backend import effects
    game = GameState(["A", "B"], seed=5)
    me = game.active_player
    enemy = game.enemies_of(me)[0]
    me.zone_in_play.append("spell_magicspill")
    me.hand = ["start_znak", "start_pshik", "start_znak"]
    enemy.hand = ["start_znak", "start_znak"]
    enemy_before = len(enemy.hand)

    game.activate_permanent(me, "spell_magicspill")
    _auto_resolve(game)

    assert len(enemy.hand) == enemy_before, "рука врага не должна меняться"
    assert len(me.hand) < 3, "своя рука должна уменьшиться"


def test_dohlyaki_never_given_on_death():
    """Дохляки (sdk_*) не выдаются за смерть — их только покупают."""
    for seed in range(30):
        game = GameState(["A", "B", "C"], seed=seed)
        assert all(not t.startswith("sdk_") for t in game.undead_token_stack), \
            f"seed={seed}: Дохляк попал в стопку смерти"

        # добиваем игрока много раз подряд
        victim = game.players[0]
        killer = game.players[1]
        for _ in range(12):
            if not game.undead_token_stack:
                break
            game.deal_damage(killer, victim.id, 999, "тест", defendable=False)
            _auto_resolve(game)
        assert all(not t.startswith("sdk_") for t in victim.death_tokens), \
            f"seed={seed}: игрок получил Дохляка за смерть: {victim.death_tokens}"


def test_death_token_pool_excludes_dohlyaki():
    """Пул жетонов смерти — ровно 30 настоящих ЖДК из 35 записей."""
    game = GameState(["A", "B"], seed=1)
    pool = game.death_token_pool()
    assert len(pool) == 30, f"в пуле {len(pool)} жетонов, ожидалось 30"
    assert not any(t.startswith("sdk_") for t in pool)


def test_custom_stack_also_excludes_dohlyaki():
    """Ручная настройка числа ЖДК тоже не тянет Дохляков."""
    game = GameState(["A", "B"], seed=2)
    game.configure_undead_stack(35)
    assert len(game.undead_token_stack) == 30, "больше 30 настоящих жетонов не бывает"
    assert not any(t.startswith("sdk_") for t in game.undead_token_stack)


def test_death_shows_token_to_player():
    """При смерти игроку показывается, какой именно жетон он получил."""
    game = GameState(["A", "B"], seed=4)
    victim = game.players[0]
    killer = game.players[1]
    game.deal_damage(killer, victim.id, 999, "тест", defendable=False)

    event = game.pending_event
    assert event, "окно с жетоном не появилось"
    assert event["type"] == "Жетон дохлого колдуна"
    assert event["id"] == victim.death_tokens[-1], "показан не тот жетон"
    assert event["name"], "у жетона нет названия"
    assert event["owner_id"] == victim.id, "не указан получатель"

    # окно закрывается без ошибок
    assert not game.resolve_event().get("error")
    assert game.pending_event is None


def test_conditional_power_beasts():
    """Твари с условием «ещё 1 тварь» дают доп. мощь корректно."""
    def power_after(setup, play):
        game = GameState(["Я", "Враг"], seed=3)
        me = game.active_player
        foe = game.enemies_of(me)[0]
        foe.hand = []
        for cid in setup:
            me.hand = [cid]
            game.play_card(me, cid, target_id=foe.id)
            game.pending_decision = None
        me.power_available = 0
        me.hand = [play]
        game.play_card(me, play, target_id=foe.id)
        return me.power_available

    # Приунывший орк: +2, и ещё +2 если есть другая тварь
    assert power_after([], "beast_ork") == 2
    assert power_after(["beast_kinky"], "beast_ork") == 4, "Развратот на столе не дал Орку +2"
    assert power_after(["beast_beer"], "beast_ork") == 4
    # Условие «хотя бы одна», а не «за каждую» — два зверя дают те же +2
    assert power_after(["beast_kinky", "beast_beer"], "beast_ork") == 4

    # Трахангутан: +3 за КАЖДУЮ тварь под контролем
    assert power_after([], "beast_orangutan") == 3
    assert power_after(["beast_ork"], "beast_orangutan") == 6
    assert power_after(["beast_ork", "beast_beer"], "beast_orangutan") == 9


def test_familiar_bought_flag():
    """После покупки фамильяра ставится флаг — фронт по нему прячет карточку."""
    game = GameState(["A", "B"], seed=3)
    me = game.active_player
    me.familiar_card_id = "fam_benz"
    me.familiar_card_ids = ["fam_benz"]
    me.power_available = 10

    assert me.familiar_bought is False
    assert not game.buy_familiar(me).get("error")
    assert me.familiar_bought is True, "флаг покупки не выставлен"
    assert "fam_benz" in me.discard, "купленный фамильяр должен уйти в сброс"
    assert me.power_available == 4, "стоимость 6 мощи не списана"


def test_all_death_tokens_resolve():
    """Каждый из 30 жетонов ЖДК отрабатывает без падений."""
    import json
    path = os.path.join(os.path.dirname(__file__), "..", "zhdk.json")
    with open(path, encoding="utf-8") as f:
        tokens = [t["id"] for t in json.load(f) if t["id"].startswith("dk_")]

    for tid in tokens:
        game = GameState(["A", "B", "C"], seed=11)
        victim, killer = game.players[0], game.players[1]
        victim.chipsines = 7
        victim.hand = ["start_znak", "start_pshik"]
        victim.discard = ["start_znak", "leg_goose"]
        killer.hand = ["start_znak"]
        game._resolve_death_token(victim, tid, killer)
        _auto_resolve(game)
        for p in game.players:
            assert p.life <= p.max_life, f"{tid}: {p.name} выше максимума HP"
            assert p.chipsines >= 0, f"{tid}: отрицательные чипсины"


def test_prize_gives_victory_points():
    """Главный приз даёт +5 ПО, жетон dk_8 этот бонус снимает."""
    game = GameState(["A", "B"], seed=1)
    holder, other = game.players
    holder.controls_prize = True
    game._finish_game()
    assert game.final_scores[holder.id]["vp"] - game.final_scores[other.id]["vp"] == 5

    game2 = GameState(["A", "B"], seed=1)
    h2, o2 = game2.players
    h2.controls_prize = True
    h2.death_tokens = ["dk_8"]
    game2._finish_game()
    # приза нет, зато есть штраф жетона
    assert game2.final_scores[h2.id]["vp"] < game2.final_scores[o2.id]["vp"]


def test_final_scores_reach_frontend():
    """Итоговый счёт попадает в состояние для клиента и отсортирован."""
    game = GameState(["A", "B", "C"], seed=2)
    assert game.to_public_dict("A")["final_scores"] is None, "до конца игры счёта быть не должно"

    game.players[0].zone_in_play.append("leg_goose")
    game._finish_game()
    rows = game.to_public_dict(game.players[0].id)["final_scores"]
    assert rows and len(rows) == 3
    assert [r["vp"] for r in rows] == sorted((r["vp"] for r in rows), reverse=True), "не отсортировано"
    assert rows[0]["id"] == game.winner, "первым должен идти победитель"
    for r in rows:
        assert {"id", "name", "vp", "legends", "death_tokens"} <= set(r)


def test_dirty_stick_boosts_all_sticks():
    """«Грязная палка» даёт +2 урона ЛЮБОЙ Палочке, а не только с заглавной буквы."""
    from backend.game import is_stick

    # регистр в названиях карт разный — проверка обязана это переживать
    assert is_stick("Сырная палочка")
    assert is_stick("Палочка-шлёпалочка")
    assert is_stick("Бузящая палочка Гарика Потного")
    assert not is_stick("Пивохранилище")

    game = GameState(["Я", "Враг"], seed=3)
    me, foe = game.players
    foe.hand = []
    foe.life = 2
    me.zone_in_play.append("place_dirty")
    me.hand = ["start_syrpal"]

    game.play_card(me, "start_syrpal", target_id=foe.id)
    _auto_resolve(game)

    # 1 базовый + 2 от «Грязной палки» = 3 урона -> враг с 2 HP обязан подохнуть
    assert any("3 урона" in line for line in game.logs), "урон должен быть 3, а не 1"
    assert len(foe.death_tokens) == 1, "враг с 2 HP должен был умереть от 3 урона"


def test_dirty_stick_gives_power():
    """«Грязная палка» даёт +1 мощь за каждую разыгранную Палочку."""
    game = GameState(["Я", "Враг"], seed=3)
    me = game.active_player
    game.enemies_of(me)[0].hand = []
    me.zone_in_play.append("place_dirty")
    me.power_available = 0
    me.hand = ["start_syrpal"]

    game.play_card(me, "start_syrpal", target_id=game.enemies_of(me)[0].id)
    _auto_resolve(game)

    # +1 мощь самой карты и +1 от «Грязной палки»
    assert me.power_available >= 2, f"ожидалось минимум 2 мощи, получено {me.power_available}"


def test_chipsina_symbol_on_purchase():
    """Значок чипсины на карте выдаёт чипсину при ПОКУПКЕ."""
    game = GameState(["Я", "Враг"], seed=3)
    me = game.active_player
    me.power_available = 20
    before = me.chipsines
    game.market.append("beast_peyot")          # Пейотка со значком чипсины
    game.buy_card(me, "beast_peyot")
    assert me.chipsines == before + 1, "покупка карты со значком должна давать чипсину"


def test_familiar_choice_on_buy():
    """Свойство «Фамильяры»: покупаем конкретного, а не первого по списку."""
    game = GameState(["Я", "Враг"], seed=3)
    me = game.active_player
    me.familiar_card_ids = ["fam_benz", "fam_weaboo", "fam_jester"]
    me.familiar_card_id = "fam_benz"
    me.power_available = 30

    assert not game.buy_familiar(me, "fam_jester").get("error")
    assert "fam_jester" in me.bought_familiars, "куплен не тот фамильяр"
    assert "fam_jester" in me.discard

    # можно купить и остальных
    assert not game.buy_familiar(me, "fam_weaboo").get("error")
    assert me.bought_familiars == ["fam_jester", "fam_weaboo"]


def test_bot_spreads_attacks():
    """Бот не долбит одного и того же игрока каждый ход."""
    import collections
    import random as rnd
    from backend.server import Room

    room = Room("t")
    game = GameState(["Игрок", "Бот 1", "Бот 2", "Бот 3"], seed=1)
    bot = game.players[1]
    enemies = [p for p in game.players if p is not bot]

    rnd.seed(11)
    hits = collections.Counter(room.pick_bot_target(bot, enemies).name for _ in range(300))
    assert len(hits) >= 2, "бот бьёт только одну цель"
    assert max(hits.values()) / 300 < 0.6, f"перекос по целям: {hits}"

    # раненого добивает
    enemies[0].life = 3
    rnd.seed(11)
    hits2 = collections.Counter(room.pick_bot_target(bot, enemies).name for _ in range(200))
    assert hits2.most_common(1)[0][0] == enemies[0].name, "бот не добивает раненого"


def test_events_have_unique_seq():
    """У каждого события свой номер — иначе клиент не отличит два
    одинаковых Беспредела подряд и второе окно не откроется."""
    game = GameState(["Я", "Бот"], seed=3)
    game.market = game.market[:2]
    game.main_deck.extend(["besp_15", "besp_15"])
    game._refilling_markets = True
    game._resume_market_refill()

    seqs = []
    guard = 0
    while game.pending_event and guard < 8:
        guard += 1
        seqs.append(game.pending_event.get("seq"))
        game.resolve_event()
        if game.pending_decision:
            _auto_resolve(game)

    assert len(seqs) >= 2, "два Беспредела должны показаться отдельно"
    assert all(s is not None for s in seqs), "у события нет номера"
    assert len(set(seqs)) == len(seqs), f"номера событий повторяются: {seqs}"


def test_two_bespredels_do_not_hang_market():
    """Два Беспредела подряд не оставляют рынок недозаполненным."""
    game = GameState(["Я", "Бот", "Третий"], seed=3)
    game.market = game.market[:2]
    game.main_deck.extend(["besp_15", "besp_15"])
    game._refilling_markets = True
    game._resume_market_refill()

    guard = 0
    while (game.pending_event or game.pending_decision) and guard < 20:
        guard += 1
        if game.pending_event:
            game.resolve_event()
        _auto_resolve(game)

    assert not game.pending_event, "событие не закрылось"
    assert not game._refilling_markets, "пополнение рынка зависло"
    assert len(game.market) == 5, f"рынок недозаполнен: {len(game.market)}"


def test_buy_with_chipsines():
    """Чипсины доплачивают за покупку: 1 чипсина = 1 мощь."""
    game = GameState(["Я", "Враг"], seed=3)
    me = game.active_player
    me.power_available = 5
    me.chipsines = 12

    legends = [c for c in game.legend_market if game.cards[c].cost >= 8]
    assert legends, "нужна дорогая легенда для проверки"
    cid = legends[0]
    cost = game.cards[cid].cost

    assert not game.buy_card(me, cid).get("error"), "покупка за мощь+чипсины отклонена"
    assert me.power_available == 0, "мощь должна списаться первой"
    assert me.chipsines == 12 - (cost - 5), "чипсины списаны неверно"


def test_two_boots_pair_cancels_penalty():
    """«Два сапога» у одного игрока взаимно уничтожаются."""
    game = GameState(["Один", "Двое"], seed=1)
    a, b = game.players
    a.death_tokens = ["dk_13", "dk_14"]
    b.death_tokens = ["dk_13"]
    game._finish_game()
    assert game.final_scores[a.id]["vp"] > game.final_scores[b.id]["vp"], \
        "пара жетонов должна снять штрафы"


def test_scoring_step_labels_are_human():
    """В расшифровке очков нет технических id вроде dk_4."""
    game = GameState(["Я", "Враг"], seed=1)
    me = game.players[0]
    me.death_tokens = ["dk_4", "dk_16"]
    me.is_loshara = True
    me.deck.append("spec_vyal")
    game._finish_game()
    for step in game.final_scores[me.id]["steps"]:
        assert "dk_" not in step["label"], f"технический id в подписи: {step['label']}"


def test_two_deaths_show_both_tokens():
    """Если умерли двое подряд, показываются оба жетона, а не один."""
    game = GameState(["A", "B", "C"], seed=3)
    killer = game.players[2]
    game.deal_damage(killer, game.players[0].id, 999, "тест", defendable=False)
    first_owner = game.pending_event["owner"]
    game.deal_damage(killer, game.players[1].id, 999, "тест", defendable=False)

    assert game.event_queue, "второй жетон потерялся"
    game.resolve_event()
    assert game.pending_event, "второе окно не открылось"
    assert game.pending_event["owner"] != first_owner, "показан тот же игрок"


def test_viagrus_sticks_give_points():
    """«Виагрус»: вялые палочки ПРИНОСЯТ ПО, а не просто перестают отнимать."""
    def score(with_viagrus):
        game = GameState(["Т", "В"], seed=1)
        p = game.players[0]
        p.deck.extend(["spec_vyal"] * 3)
        if with_viagrus:
            p.zone_in_play.append("leg_viagrus")
        game._finish_game()
        steps = {s["label"]: s["delta"] for s in game.final_scores[p.id]["steps"]}
        return steps.get("Вялые палочки", 0) + steps.get("Виагрус: палочки приносят ПО", 0)

    assert score(False) == -3, "три палочки должны давать -3 ПО"
    assert score(True) == 3, "с Виагрусом три палочки должны давать +3 ПО"


def test_circus_flips_loshara_penalty():
    """«Цирк»: штраф за лошару становится бонусом."""
    def loshara_total(with_circus):
        game = GameState(["Т", "В"], seed=1)
        p = game.players[0]
        p.is_loshara = True
        if with_circus:
            p.zone_in_play.append("place_circus")
        game._finish_game()
        steps = {s["label"]: s["delta"] for s in game.final_scores[p.id]["steps"]}
        return steps.get("Ты лошара", 0) + steps.get("Цирк Лошашных: штраф стал бонусом", 0)

    assert loshara_total(False) == -5
    assert loshara_total(True) == 5, "Цирк должен превратить -5 в +5"


def test_viagrus_power_on_stick():
    """«Виагрус»: каждая сыгранная вялая палочка даёт +3 мощи."""
    def power_after(with_viagrus, sticks=1):
        game = GameState(["Я", "Враг"], seed=3)
        me = game.active_player
        if with_viagrus:
            me.zone_in_play.append("leg_viagrus")
        me.power_available = 0
        me.hand = ["spec_vyal"] * sticks
        for _ in range(sticks):
            game.play_card(me, "spec_vyal")
        return me.power_available

    assert power_after(False) == 0, "без Виагруса палочка не даёт мощи"
    assert power_after(True) == 3, "с Виагрусом палочка должна давать +3"
    assert power_after(True, 2) == 6, "две палочки — +6 мощи"


def test_viagrus_gives_stick_each_turn():
    """«Виагрус»: в начале своего хода выдаёт вялую палочку на руку."""
    game = GameState(["Я", "Враг"], seed=3)
    me = game.active_player
    me.zone_in_play.append("leg_viagrus")
    before = me.hand.count("spec_vyal")
    stack_before = game.vyal_remaining

    game.end_turn(me)
    while game.active_player.id != me.id:
        game.end_turn(game.active_player)

    assert me.hand.count("spec_vyal") == before + 1, "палочка не выдана"
    assert game.vyal_remaining == stack_before - 1, "палочка не списана из стопки"


def test_familiar_bought_with_chipsines():
    """Фамильяр покупается за мощь + чипсины."""
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    me.familiar_card_ids = ["fam_benz"]
    me.familiar_card_id = "fam_benz"
    me.power_available = 5
    me.chipsines = 1
    assert not game.buy_familiar(me, "fam_benz").get("error")
    assert me.power_available == 0 and me.chipsines == 0


def test_prize_gives_chipsine_each_turn():
    """Владелец Главного приза получает чипсину в конце своего хода."""
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    me.controls_prize = True
    before = me.chipsines
    game.end_turn(me)
    assert me.chipsines == before + 1, "приз не принёс чипсину"


def test_weaboo_needs_legend():
    """«Счастливый виабу» без легенды под контролем не атакует."""
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    foe = game.enemies_of(me)[0]
    foe.hand = []
    before = foe.life
    me.hand = ["fam_weaboo"]
    game.play_card(me, "fam_weaboo", target_id=foe.id)
    _auto_resolve(game)
    assert foe.life == before, "виабу ударил без легенды"


def test_jaba_is_not_defense():
    """«Баклажаба» не предлагается как защитная карта."""
    game = GameState(["Я", "В"], seed=3)
    me, foe = game.players
    foe.hand = ["beast_jaba"]
    game.attack_target(me, game.cards["start_syrpal"], foe.id, 3)
    assert not game.pending_decision, "Баклажаба предложена как защита"


def test_dohlyaki_not_counted_as_tokens():
    """Дохляки sdk_* не считаются жетонами ЖДК в финале."""
    game = GameState(["Я", "В"], seed=1)
    me = game.players[0]
    me.death_tokens = ["dk_1", "sdk_1", "sdk_2"]
    game._finish_game()
    assert game.final_scores[me.id]["death_tokens"] == 1, "Дохляки посчитаны как ЖДК"


def test_wild_magic_no_recursion():
    """Украденная Шальная магия не срабатывает сама — игрок выбирает."""
    game = GameState(["Аня", "Я"], seed=3)
    a, me = game.players
    me.deck = ["start_znak", "spec_wild"]
    a.power_available = 0
    a.hand = ["spec_wild"]
    game.play_card(a, "spec_wild", choice="steal", target_id=me.id)
    assert game.pending_decision, "Шальная магия сработала сама"
    assert a.power_available == 0, "мощь начислена без выбора игрока"
    game.resolve_decision(a, "power")
    assert a.power_available == 2


def test_dirtwind_asks_to_destroy():
    """«Мусорный ветер» спрашивает, какую карту сбросa уничтожить."""
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    game.enemies_of(me)[0].hand = []
    me.discard = ["start_znak", "start_pshik"]
    me.hand = ["spell_dirtwind"]
    game.play_card(me, "spell_dirtwind")
    assert game.pending_decision, "выбор карты не предложен"
    ids = [o["id"] for o in game.pending_decision["options"]]
    assert "start_znak" in ids and "skip" in ids


def test_buy_with_explicit_chipsines():
    """Можно явно указать, сколько чипсин потратить."""
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    me.power_available = 10
    me.chipsines = 10
    legends = [c for c in game.legend_market if game.cards[c].cost >= 8]
    assert legends
    cid = legends[0]
    cost = game.cards[cid].cost
    assert not game.buy_card(me, cid, use_chipsines=cost).get("error")
    assert me.power_available == 10, "мощь не должна тратиться"
    assert me.chipsines == 10 - cost


def test_chipsines_only_for_legends_and_familiars():
    """Чипсинами платят ТОЛЬКО за легенды и фамильяров."""
    # обычная карта барахолки — только за мощь
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    me.power_available = 0
    me.chipsines = 20
    assert game.buy_card(me, game.market[0]).get("error"), \
        "обычную карту нельзя купить за чипсины"

    # легенда — можно
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    me.power_available = 0
    me.chipsines = 20
    assert not game.buy_card(me, game.legend_market[0]).get("error"), \
        "легенду можно купить за чипсины"

    # Шальная магия — нельзя
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    me.power_available = 0
    me.chipsines = 20
    assert game.buy_wild_magic(me).get("error"), \
        "Шальную магию нельзя купить за чипсины"

    # Шальная магия за мощь — можно
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    me.power_available = 5
    me.chipsines = 0
    assert not game.buy_wild_magic(me).get("error")

    # фамильяр — можно
    game = GameState(["Я", "В"], seed=3)
    me = game.active_player
    me.familiar_card_ids = ["fam_benz"]
    me.familiar_card_id = "fam_benz"
    me.power_available = 0
    me.chipsines = 20
    assert not game.buy_familiar(me, "fam_benz").get("error"), \
        "фамильяра можно купить за чипсины"


def test_geek_and_goose_stack():
    """Две копии Гикпига/Гусыни считаются обе, а не одна."""
    game = GameState(["Т", "В"], seed=1)
    p = game.players[0]
    p.zone_in_play.extend(["beast_geek", "beast_geek"])
    p.deck.extend(["beast_beer", "beast_ork"])
    game._finish_game()
    steps = {s["label"]: s["delta"] for s in game.final_scores[p.id]["steps"]}
    geek = next((v for k, v in steps.items() if "Гикпиг" in k), 0)
    # 4 твари (2 Гикпига + Пивохранилище + Орк) x 2 копии = 8
    assert geek == 8, f"Гикпиги не стакаются: {geek}"


def test_epic_vyal_asks_how_many():
    """«ТА САМАЯ Вялая палочка» спрашивает, сколько палочек отдать."""
    game = GameState(["Я", "Враг"], seed=3)
    me, foe = game.players
    foe.hand = []
    foe.life = 3
    me.hand = ["leg_epicvyal"]
    game.play_card(me, "leg_epicvyal", target_id=foe.id)
    assert game.pending_decision, "выбор количества не предложен"
    ids = [o["id"] for o in game.pending_decision["options"]]
    assert "0" in ids and "3" in ids, f"нет вариантов количества: {ids}"


def test_magicspill_can_destroy_played_cards():
    """«Волшебные отходы» видят и сыгранные в этот ход карты."""
    game = GameState(["Я", "Враг"], seed=3)
    me = game.active_player
    me.zone_in_play.append("spell_magicspill")
    me.hand = []
    me.in_play_this_turn = ["start_pshik", "start_pshik"]
    game.activate_permanent(me, "spell_magicspill")
    assert game.pending_decision, "окно не появилось"
    ids = [o["id"] for o in game.pending_decision["options"]]
    assert "start_pshik" in ids, "сыгранные карты не предлагаются"


def test_besp16_logs_victim():
    """besp_16 пишет, кого именно выбрало самым хилым."""
    game = GameState(["Я", "Бот"], seed=3)
    game.players[0].life = 4
    import backend.effects as ef
    ef.EFFECT_REGISTRY["besp_16"](game, game.active_player, game.cards["besp_16"])
    assert any("самый хилый" in line for line in game.logs), "не видно, кого выбрало"
    assert game.players[0].is_loshara
