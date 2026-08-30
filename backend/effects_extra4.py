"""Массовые Беспределы и Мегабеспределы."""
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


@effect("besp_1")
def besp_1(game, player, card, **kw):
    entries=[]
    for target in game.players:
        if target.hand:
            expensive_id = max(target.hand, key=lambda cid: game.cards[cid].cost)
            max_cost = game.cards[expensive_id].cost
            game.log(f"БЕСПРЕДЕЛ: {target.name} — самая дорогая «{game.cards[expensive_id].name}» ({max_cost})")
        else:
            max_cost = 0
            game.log(f"БЕСПРЕДЕЛ: у {target.name} нет карт на руке (0 урона)")
        entries.append((target,max_cost))
    game.declare_variable_attack(player,card,entries)


@effect("besp_2")
def besp_2(game, player, card, **kw):
    for target in game.players:
        target.discard.extend(target.deck); target.deck = []
    def apply(target, choice):
        if choice != "skip":
            zone, cid = choice.split(":", 1)
            game.destroy_from_zone(target, cid, zone)
    game.request_decision_sequence(game.players, "БЕСПРЕДЕЛ: чистка сброса", lambda p: "Колода сброшена. Уничтожь 1 карту из сброса или откажись.", lambda p: destroy_options(game,p,["discard"]), apply)


@effect("besp_3")
def besp_3(game, player, card, **kw):
    for cid in game.market:
        game.market_chips[cid] = game.market_chips.get(cid, 0) + 1
    game.log("БЕСПРЕДЕЛ: на каждую карту барахолки положена чипсина")


@effect("besp_4")
def besp_4(game, player, card, **kw):
    def apply(target, choice):
        if choice != "skip":
            if target.is_loshara: target.life -= 3
            zone,cid=choice.split(":",1); game.destroy_from_zone(target,cid,zone)
    game.request_decision_sequence(game.players,"БЕСПРЕДЕЛ: уничтожение",lambda p:"Можешь уничтожить 1 карту с руки или из сброса. Лошара платит 3 жизни.",lambda p:destroy_options(game,p,["hand","discard"]),apply)


@effect("besp_5")
def besp_5(game, player, card, **kw):
    participants = list(game.players)
    def process_player(index):
        if index >= len(participants):
            return
        target = participants[index]
        if not target.hand:
            process_player(index + 1)
            return
        def reveal_again():
            if not target.hand:
                process_player(index + 1)
                return
            cid = game.rng.choice(target.hand)
            revealed = game.cards[cid]
            options = [{"id":"destroy","label":f"Уничтожить «{revealed.name}»"}]
            if target.life > 2:
                options.append({"id":"reroll","label":"Потратить 2 жизни и раскрыть другую"})
            def decide(choice):
                if choice == "destroy":
                    target.hand.remove(cid)
                    game.destroyed_pile.append(cid)
                    game.log(f"{target.name}: уничтожает «{revealed.name}»")
                    process_player(index + 1)
                else:
                    target.life -= 2
                    reveal_again()
            game.request_decision(target, "БЕСПРЕДЕЛ: случайная карта", f"Раскрыта «{revealed.name}». Уничтожить её или потратить 2 жизни и раскрыть другую?", options, decide)
        reveal_again()
    process_player(0)


@effect("besp_6")
def besp_6(game, player, card, **kw):
    def apply(target, choice):
        if choice == "redraw":
            target.discard.extend(target.hand); target.hand=[]; game.draw_cards(target,5)
        else: game.deal_damage(player,target.id,5,card.name,defendable=False)
    game.request_decision_sequence(game.players,"БЕСПРЕДЕЛ: выбор",lambda p:"Сбросить руку и взять 5 карт или отхватить 5 урона?",lambda p:[{"id":"damage","label":"Получить 5 урона"},{"id":"redraw","label":"Сбросить руку и взять 5 карт"}],apply)


@effect("besp_7")
def besp_7(game, player, card, **kw):
    participants = []
    def apply(target, choice):
        if choice == "join":
            participants.append(target)
    def finish():
        if not participants:
            return
        totals = {p.id: sum(game.cards[cid].cost for cid in p.hand) for p in participants}
        best = max(totals.values())
        for target in participants:
            if totals[target.id] == best:
                game.draw_cards(target, 2)
            else:
                target.discard.extend(target.hand)
                target.hand = []
        game.log("БЕСПРЕДЕЛ: баттл «Кто круче» завершён")
    game.request_decision_sequence(
        game.players,
        "БЕСПРЕДЕЛ: Кто круче",
        lambda p: "Участвовать? Участники раскрывают руки; максимум стоимости берёт 2 карты.",
        lambda p: [{"id":"join","label":"Участвовать"},{"id":"pass","label":"Пас"}],
        apply,
        finish,
    )


@effect("besp_8")
def besp_8(game, player, card, **kw):
    for target in game.players:
        target.chipsines += 2
    game.declare_variable_attack(player, card, [(target, target.chipsines) for target in game.players if target.is_alive()])


@effect("besp_9")
def besp_9(game, player, card, **kw):
    game.destroyed_pile.extend(game.legend_market); game.legend_market=[]
    while len(game.legend_market) < 4 and game.legend_deck:
        cid=game.legend_deck.pop()
        if game.cards[cid].type == "Мегабеспредел":
            game._resolve_besp(game.cards[cid]); game.destroyed_besp_pile.append(cid)
        else: game.legend_market.append(cid)


@effect("besp_10")
def besp_10(game, player, card, **kw):
    votes = []
    def options(current):
        return [{"id": target.id, "label": target.name} for target in game.players]
    def apply(current, choice):
        votes.append(choice)
    def finish():
        if not votes:
            return
        counts = {pid: votes.count(pid) for pid in set(votes)}
        high = max(counts.values())
        for pid, count in counts.items():
            if count == high:
                target = game.get_player(pid)
                if target:
                    game.set_loshara(target, True)
        game.log("БЕСПРЕДЕЛ: голосование за лошару завершено")
    game.request_decision_sequence(game.players, "БЕСПРЕДЕЛ: голосование", lambda p: "Выбери любого колдуна. Больше всего голосов — лошара.", options, apply, finish)


@effect("besp_11")
def besp_11(game, player, card, **kw):
    for target in game.players: target.chipsines += 1
    game.destroyed_pile.extend(game.legend_market); game.legend_market=[]; game._fill_legend_market_resolving()


@effect("besp_12")
def besp_12(game, player, card, **kw):
    participants = list(game.players)
    def ask_next(index):
        if index >= len(participants):
            return
        target = participants[index]
        count = (len(target.zone_in_play) + 1) // 2
        def discard_many(left):
            if left <= 0 or not target.zone_in_play:
                ask_next(index + 1)
                return
            options = [{"id": cid, "label": game.cards[cid].name} for cid in target.zone_in_play]
            def apply(choice):
                if choice in target.zone_in_play:
                    target.zone_in_play.remove(choice)
                    target.discard.append(choice)
                discard_many(left - 1)
            game.request_decision(target, "БЕСПРЕДЕЛ: половина постоянок", f"Выбери постоянку для сброса. Осталось сбросить: {left}.", options, apply)
        discard_many(count)
    ask_next(0)


@effect("besp_13")
def besp_13(game, player, card, **kw):
    game.request_decision_sequence(game.players,"БЕСПРЕДЕЛ: жизни за чипсину",lambda p:"Свести жизни к 10 и получить 1 чипсину?",lambda p:[{"id":"yes","label":"Свести жизни к 10, получить чипсину"},{"id":"no","label":"Отказаться"}],lambda p,c: (setattr(p,"life",10),setattr(p,"chipsines",p.chipsines+1)) if c=="yes" else None)


@effect("besp_14")
def besp_14(game, player, card, **kw):
    def opts(current): return [{"id":p.id,"label":p.name} for p in game.enemies_of(current)]
    def apply(current, choice):
        target=game.get_player(choice)
        if target: target.chipsines += 1
    game.request_decision_sequence(game.players,"БЕСПРЕДЕЛ: чипсина врагу",lambda p:"Выбери врага: он получит 1 чипсину.",opts,apply)


@effect("besp_15")
def besp_15(game, player, card, **kw):
    for target in game.players:
        if not target.is_loshara: target.chipsines += 1


@effect("besp_16")
def besp_16(game, player, card, **kw):
    """Самый хилый становится лошарой и лечится до лошарного максимума."""
    living = [p for p in game.players if p.is_alive()]
    if not living:
        return
    lowest = min(p.life for p in living)
    victims = [p for p in living if p.life == lowest]
    names = ", ".join(p.name for p in victims)
    game.log(f"{card.name}: самый хилый — {names} ({lowest} HP)")
    for target in victims:
        game.set_loshara(target, True)
        target.life = target.max_life
        game.log(f"{target.name}: становится лошарой и лечится до {target.life} HP")


@effect("besp_17")
def besp_17(game, player, card, **kw): game.declare_attack(player,card,all_players(game),5)


@effect("besp_18")
def besp_18(game, player, card, **kw):
    revealed={}
    for target in game.players:
        cards=[]
        for _ in range(2):
            if not target.deck: game.reshuffle_discard_into_deck(target)
            if target.deck: cards.append(target.deck.pop())
        target.discard.extend(cards); revealed[target.id]=cards
    def opts(target): return [{"id":"destroy","label":"Уничтожить обе карты"},{"id":"keep","label":"Оставить обе в сбросе"}] if revealed[target.id] else [{"id":"keep","label":"Нечего уничтожать"}]
    def apply(target, choice):
        if choice=="destroy":
            for cid in revealed[target.id][:]:
                if cid in target.discard: game.destroy_from_zone(target,cid,"discard")
    def text(target):
        names=[game.cards[c].name for c in revealed[target.id]]
        return ("Сброшены: "+", ".join(names)+". Уничтожить обе или оставить?") if names else "Колода пуста"
    game.request_decision_sequence(game.players,"БЕСПРЕДЕЛ: две верхние карты",text,opts,apply,
                                   cards_for_player=lambda t: revealed.get(t.id, []))


@effect("besp_19")
def besp_19(game, player, card, **kw):
    def apply(target, choice):
        if choice=="life":
            target.life -= 5
            game.set_loshara(target, False)
        elif choice=="chip":
            target.chipsines -= 1
            game.set_loshara(target, False)
    losers=[p for p in game.players if p.is_loshara]
    game.request_decision_sequence(losers,"БЕСПРЕДЕЛ: стать нормальным",lambda p:"Потратить 5 жизней или 1 чипсину, чтобы стать нормальным?",lambda p:([{"id":"life","label":"Потратить 5 жизней"}] if p.life>5 else [])+([{"id":"chip","label":"Потратить 1 чипсину"}] if p.chipsines else [])+[{"id":"no","label":"Остаться лошарой"}],apply)


@effect("mega_1")
def mega_1(game, player, card, **kw):
    amount=max((game.cards[cid].cost for cid in game.legend_market),default=0)
    game.declare_attack(player,card,all_players(game),amount)

@effect("mega_2")
def mega_2(game, player, card, **kw):
    # Атака: защита отменяет получение трёх Вялых палочек.
    game.declare_attack(player, card, all_players(game), 0, on_hit=lambda target, dead: game.give_weak_sticks(target, 3, "hand"))

@effect("mega_3")
def mega_3(game, player, card, **kw):
    # Атака: защищающийся не меняет статус.
    def toggle(target, dead):
        game.set_loshara(target, not target.is_loshara)
    game.declare_attack(player, card, all_players(game), 0, on_hit=toggle)

def request_destroy_many(game, player, count, title, text, done=None):
    """Дать одному игроку уничтожить до count карт из руки/сброса."""
    def step(left):
        if left <= 0:
            if done: done()
            return
        options = destroy_options(game, player, ["hand", "discard"])
        def apply(choice):
            if choice == "skip":
                if done: done()
                return
            zone, cid = choice.split(":", 1)
            game.destroy_from_zone(player, cid, zone)
            step(left - 1)
        game.request_decision(player, title, text if left == count else "Можешь уничтожить ещё одну карту или закончить.", options, apply)
    step(count)


@effect("besp_20")
def besp_20(game, player, card, **kw):
    candidates = [p for p in game.players if p.chipsines > 0]
    def ask_next(index):
        if index >= len(candidates):
            return
        target = candidates[index]
        cost = target.chipsines // 2
        if cost <= 0:
            ask_next(index + 1)
            return
        def choose(choice):
            if choice == "yes":
                target.chipsines -= cost
                request_destroy_many(game, target, 1, "БЕСПРЕДЕЛ: уничтожение", f"Потрачено {cost} чипсин. Уничтожь карту.", lambda: ask_next(index + 1))
            else:
                ask_next(index + 1)
        game.request_decision(target, "БЕСПРЕДЕЛ: половина чипсин", f"Потерять {cost} чипсин, чтобы уничтожить карту с руки или из сброса?", [{"id":"yes","label":f"Потратить {cost} чипсин"},{"id":"no","label":"Отказаться"}], choose)
    ask_next(0)


@effect("mega_4")
def mega_4(game, player, card, **kw):
    participants = list(game.players)
    def ask_next(index):
        if index >= len(participants):
            return
        target = participants[index]
        count = 2 if not target.is_loshara else 1
        request_destroy_many(game, target, count, "МЕГАБЕСПРЕДЕЛ: уничтожение", f"Можешь уничтожить до {count} карт(ы) с руки или из сброса.", lambda: ask_next(index + 1))
    ask_next(0)


@effect("mega_5")
def mega_5(game, player, card, **kw):
    def destroy_top(target, dead):
        if not game.main_deck:
            game.log(f"{card.name}: основная колода пуста — уничтожать нечего")
            return
        cid = game.main_deck.pop()
        destroyed = game.cards[cid]
        game.destroyed_pile.append(cid)
        # Показываем, ЧТО вскрыли: раньше карта уничтожалась молча.
        game.log(f"{target.name}: уничтожает верхнюю карту — «{destroyed.name}» ({destroyed.type})")
        game.emit_visual_event("destroy", target, [cid], "deck", "destroyed")
        is_besp = destroyed.type in ("Беспредел", "Мегабеспредел")
        # Карта горит на экране у ВСЕХ: картинкой, названием и текстом.
        game.announce_destroy(
            cid,
            reason=(f"{card.name} — это беспредел, {target.name} подыхает!"
                    if is_besp else f"{card.name}: {target.name} сжигает верхнюю карту барахолки"),
            victim=target,
        )
        if is_besp:
            game.log(f"{target.name}: это беспредел — он подыхает!")
            game.deal_damage(player, target.id, target.life, card.name, defendable=False)
    game.declare_attack(player, card, all_players(game), 0, on_hit=destroy_top)


@effect("mega_6")
def mega_6(game, player, card, **kw):
    game.declare_attack(player, card, all_players(game), 0, on_hit=lambda target, dead: setattr(target, "life", min(target.life, 5)))

@effect("mega_7")
def mega_7(game, player, card, **kw):
    for target in game.players: target.chipsines += len(target.death_tokens)
