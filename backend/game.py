"""
Игровой движок Крутагидона. Не знает про сеть/WebSocket — чистая логика,
чтобы её можно было гонять и тестировать без сервера.
"""
from __future__ import annotations
import json
import os
import random
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable

from .models import (
    Card, load_all_cards, MAIN_DECK_TYPES, LEGEND_DECK_TYPES,
    STARTER_TYPES, WILD_MAGIC_TYPE, WEAK_STICK_TYPE, FAMILIAR_TYPE,
)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..")


def load_zhdk() -> dict[str, dict]:
    path = os.path.join(_DATA_DIR, "zhdk.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return {r["id"]: r for r in rows}

STARTER_DECK_RECIPE = {
    "start_znak": 6,
    "start_syrpal": 1,
    "start_pshik": 3,
}

MAX_LIFE = 25
START_LIFE = 20
LOSHARA_MAX_LIFE = 15
HAND_SIZE = 5
MARKET_SIZE = 5
LEGEND_MARKET_SIZE = 3


@dataclass
class Player:
    id: str
    name: str
    avatar: str = "🧙"
    life: int = START_LIFE
    max_life: int = MAX_LIFE
    chipsines: int = 0
    death_tokens: list = field(default_factory=list)   # ids жетонов ЖДК
    is_loshara: bool = False
    familiar_card_id: Optional[str] = None  # основной фамильяр, совместимость с текущей покупкой
    familiar_card_ids: list = field(default_factory=list)  # все фамильяры игрока (свойство svo_2 даёт три)
    familiar_bought: bool = False
    property_id: Optional[str] = None
    controls_prize: bool = False

    deck: list = field(default_factory=list)      # stack, top = end of list
    hand: list = field(default_factory=list)
    discard: list = field(default_factory=list)
    zone_in_play: list = field(default_factory=list)   # постоянки, лежащие "в игре"

    power_available: int = 0
    in_play_this_turn: list = field(default_factory=list)  # сыгранные в этот ход
    available_attacks: list = field(default_factory=list)  # атаки, отложенные до конца хода
    received_this_turn: list = field(default_factory=list)
    hand_limit_bonus: int = 0

    just_died: bool = False   # флаг для однократных проверок в этот резолв

    def is_alive(self) -> bool:
        return self.life > 0


class GameState:
    def __init__(self, player_names: list[str], seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.cards: dict[str, Card] = load_all_cards()
        self.zhdk: dict[str, dict] = load_zhdk()
        self.players: list[Player] = [
            Player(id=str(uuid.uuid4())[:8], name=n) for n in player_names
        ]
        self.turn_idx = 0
        self.game_over = False
        self.winner: Optional[str] = None
        self.logs: list[str] = []

        self.main_deck: list[str] = []
        self.market: list[str] = []
        self.legend_deck: list[str] = []
        self.legend_market: list[str] = []
        self.wild_magic_remaining = 0
        self.vyal_remaining = 0
        self.destroyed_pile: list[str] = []            # уничтоженные обычные
        self.destroyed_besp_pile: list[str] = []        # уничтоженные беспределы
        self.undead_token_stack: list[str] = []          # доступные ЖДК
        self.prize_holder: Optional[str] = None

        self.pending_attack: Optional[dict] = None
        # Универсальная пауза движка: игрок должен выбрать карту/цель/вариант.
        # Callback живёт только в памяти текущей комнаты, что подходит модели без БД.
        self.pending_decision: Optional[dict] = None
        self._decision_callback: Optional[Callable] = None
        self.last_damage_target_id: Optional[str] = None

        self._setup()

    # ------------------------------------------------------------------ #
    # Подготовка партии
    # ------------------------------------------------------------------ #
    def _setup(self):
        for p in self.players:
            for card_id, qty in STARTER_DECK_RECIPE.items():
                p.deck.extend([card_id] * qty)
            self.rng.shuffle(p.deck)
            self.draw_cards(p, HAND_SIZE)

        main_pool = []
        for c in self.cards.values():
            if c.type in MAIN_DECK_TYPES:
                main_pool.extend([c.id] * max(c.qty_in_deck, 1))
        self.rng.shuffle(main_pool)
        self.main_deck = main_pool

        legend_pool = []
        for c in self.cards.values():
            if c.type in LEGEND_DECK_TYPES:
                legend_pool.extend([c.id] * max(c.qty_in_deck, 1))
        self.rng.shuffle(legend_pool)
        self.legend_deck = legend_pool

        wild_card = next((c for c in self.cards.values() if c.type == WILD_MAGIC_TYPE), None)
        self.wild_magic_remaining = wild_card.qty_in_deck if wild_card else 15
        vyal_card = next((c for c in self.cards.values() if c.type == WEAK_STICK_TYPE), None)
        self.vyal_remaining = vyal_card.qty_in_deck if vyal_card else 15

        # барахолка без беспределов (по правилам, стр.6)
        self._fill_market_no_resolve()
        self._fill_legend_market_no_resolve()

        # ЖДК берём из отдельного файла zhdk.json (лист "Жетоны дохлых колдунов")
        undead_ids = list(self.zhdk.keys())
        self.rng.shuffle(undead_ids)
        self.undead_token_stack = undead_ids[: 4 * len(self.players)] if undead_ids else []

        self.log("Партия подготовлена. Первый ход у " + self.players[0].name)

    def configure_undead_stack(self, count: int):
        """Переопределить число ЖДК перед стартом партии настройкой комнаты."""
        ids = list(self.zhdk.keys())
        self.rng.shuffle(ids)
        self.undead_token_stack = ids[:max(0, min(int(count), len(ids)))]

    def apply_property_setup(self, player: Player):
        """Начальные эффекты свойств, которые обязаны сработать до первого хода."""
        if player.property_id == "svo_6":
            player.life = MAX_LIFE
            player.max_life = MAX_LIFE
            if self.prize_holder:
                old = self.get_player(self.prize_holder)
                if old:
                    old.controls_prize = False
            self.prize_holder = player.id
            player.controls_prize = True
            self.turn_idx = self.players.index(player)
            self.log(f"{player.name}: свойство «Главный приз» — начинает с призом и ходит первым")
        elif player.property_id == "svo_10":
            # Меняем ровно один Знак вне зависимости от того, успел ли он попасть в стартовую руку.
            for zone in (player.hand, player.deck):
                if "start_znak" in zone:
                    zone[zone.index("start_znak")] = "start_hrenal"
                    self.log(f"{player.name}: свойство заменяет Знак на Палочку-хреналочку")
                    break

    def _fill_market_no_resolve(self):
        while len(self.market) < MARKET_SIZE and self.main_deck:
            cid = self.main_deck.pop()
            card = self.cards[cid]
            if card.type == "Беспредел":
                self.destroyed_besp_pile.append(cid)
                continue
            self.market.append(cid)

    def _fill_legend_market_no_resolve(self):
        while len(self.legend_market) < LEGEND_MARKET_SIZE and self.legend_deck:
            cid = self.legend_deck.pop()
            card = self.cards[cid]
            if card.type == "Мегабеспредел":
                self.destroyed_besp_pile.append(cid)
                continue
            self.legend_market.append(cid)

    # ------------------------------------------------------------------ #
    # Утилиты
    # ------------------------------------------------------------------ #
    def log(self, msg: str):
        self.logs.append(msg)

    def get_player(self, pid: str) -> Optional[Player]:
        return next((p for p in self.players if p.id == pid), None)

    @property
    def active_player(self) -> Player:
        return self.players[self.turn_idx]

    def enemies_of(self, player: Player) -> list[Player]:
        return [p for p in self.players if p.id != player.id and p.is_alive()]

    def controlled_card_ids(self, player: Player) -> list[str]:
        """Карты под контролем в текущий момент: сыгранные в ход и постоянки."""
        return player.zone_in_play + player.in_play_this_turn

    def count_controlled_type(self, player: Player, card_type: str, exclude_id: Optional[str] = None) -> int:
        return sum(
            1 for cid in self.controlled_card_ids(player)
            if cid != exclude_id and card_type in self.cards[cid].types_for_matching
        )

    def heal(self, player: Player, amount: int):
        player.life = min(player.max_life, player.life + max(0, amount))

    def destroy_from_zone(self, player: Player, card_id: str, zone: str) -> bool:
        cards = getattr(player, zone, None)
        if not isinstance(cards, list) or card_id not in cards:
            return False
        cards.remove(card_id)
        self.destroyed_pile.append(card_id)
        self.log(f"{player.name}: уничтожает «{self.cards[card_id].name}»")
        return True

    def hand_limit(self, player: Player) -> int:
        # «Длань творца» даёт постоянный предел руки, пока находится на столе.
        dlan_bonus = sum(1 for cid in player.zone_in_play if cid == "place_dlan")
        park_bonus = 2 if "leg_park" in player.zone_in_play and player.life >= player.max_life else 0
        return HAND_SIZE + player.hand_limit_bonus + dlan_bonus + park_bonus

    def reshuffle_discard_into_deck(self, player: Player):
        if not player.deck and player.discard:
            player.deck = player.discard[:]
            player.discard = []
            self.rng.shuffle(player.deck)
            self.log(f"{player.name}: колода пуста, сброс перемешан в новую колоду")

    def draw_cards(self, player: Player, n: int):
        for _ in range(n):
            if not player.deck:
                self.reshuffle_discard_into_deck(player)
            if not player.deck:
                break  # совсем нечего брать
            player.hand.append(player.deck.pop())

    def give_weak_sticks(self, player: Player, count: int, destination: str = "hand"):
        given = min(max(0, count), self.vyal_remaining)
        for _ in range(given):
            if destination == "deck_bottom":
                player.deck.insert(0, "spec_vyal")
            elif destination == "discard":
                player.discard.append("spec_vyal")
            else:
                player.hand.append("spec_vyal")
        self.vyal_remaining -= given
        if given:
            self.log(f"{player.name}: получает {given} Вял. палочк.")
        return given

    def receive_card(self, player: Player, card_id: str, destination: str = "discard"):
        """Единая точка получения карты: покупки, фамильяры и эффекты.
        Здесь срабатывают свойства, завязанные на «получение» карты.
        """
        card = self.cards[card_id]
        player.received_this_turn.append(card_id)
        if destination == "hand":
            player.hand.append(card_id)
        elif destination == "deck_top":
            player.deck.append(card_id)
        else:
            player.discard.append(card_id)

        if card_id == "place_vyaltower":
            self.give_weak_sticks(player, 2, "discard")

        if player.property_id == "svo_9" and "Волшебник" in card.types_for_matching:
            player.chipsines += 1
            if player.is_loshara:
                player.is_loshara = False
            self.log(f"{player.name}: свойство «Волшебное разлошаривание» — +1 чипсина")

        # Два свойства позволяют вместо сброса положить полученную карту наверх колоды.
        top_reason = None
        if destination == "discard" and player.property_id == "svo_5" and card.postoyanka:
            top_reason = "постоянку"
        elif destination == "discard" and player.property_id == "svo_8" and "Тварь" in card.types_for_matching:
            top_reason = "тварь"
        elif destination == "discard" and "place_souv" in player.zone_in_play and "Легенда" in card.types_for_matching:
            top_reason = "легенду"
        if top_reason:
            def place_top(choice: str, cid=card_id):
                if choice == "top" and cid in player.discard:
                    player.discard.remove(cid)
                    player.deck.append(cid)
                    self.log(f"{player.name}: кладёт «{self.cards[cid].name}» на верх колоды")
            self.request_decision(
                player,
                "Куда положить карту?",
                f"Свойство позволяет положить полученную карту ({top_reason}) на верх своей колоды.",
                [{"id": "top", "label": "На верх колоды"}, {"id": "discard", "label": "Оставить в сбросе"}],
                place_top,
            )

    # ------------------------------------------------------------------ #
    # Выборы игрока / паузы движка
    # ------------------------------------------------------------------ #
    def request_decision(self, player: Player, title: str, text: str,
                         options: list[dict], callback: Callable):
        """Остановить разрешение эффекта и показать игроку безопасный список вариантов.

        options: [{id, label, detail?}]. Сами карты/цели остаются валидируемыми
        на сервере в callback — клиент лишь выбирает один из уже предложенных id.
        """
        self.pending_decision = {
            "player_id": player.id,
            "player_name": player.name,
            "title": title,
            "text": text,
            "options": options,
        }
        self._decision_callback = callback

    def resolve_decision(self, player: Player, option_id: str) -> dict:
        pending = self.pending_decision
        if not pending:
            return {"error": "Сейчас нет выбора, который нужно подтвердить"}
        if pending["player_id"] != player.id:
            return {"error": "Этот выбор ожидается от другого игрока"}
        allowed = {str(option["id"]) for option in pending["options"]}
        if str(option_id) not in allowed:
            return {"error": "Такого варианта нет"}
        callback = self._decision_callback
        self.pending_decision = None
        self._decision_callback = None
        if callback:
            callback(str(option_id))
        return {"ok": True}

    def request_decision_sequence(self, players: list[Player], title: str, text_for_player: Callable,
                                  options_for_player: Callable, apply_choice: Callable, done: Optional[Callable] = None):
        """Последовательно спросить решение у нескольких игроков.
        Нужен Беспределам: не даёт одному игроку принимать выбор за всех.
        """
        def step(index: int):
            if index >= len(players):
                if done:
                    done()
                return
            current = players[index]
            options = options_for_player(current)
            if not options:
                step(index + 1)
                return
            def resolve(choice: str):
                apply_choice(current, choice)
                step(index + 1)
            self.request_decision(current, title, text_for_player(current), options, resolve)
        step(0)

    # ------------------------------------------------------------------ #
    # Ход
    # ------------------------------------------------------------------ #
    def start_turn(self):
        self._fill_market_resolving()
        self._fill_legend_market_resolving()
        p = self.active_player
        p.power_available = 0
        p.in_play_this_turn = []
        p.available_attacks = []
        p.received_this_turn = []
        p.legend_discount_turn = 0
        p.market_to_hand_turn = False
        # Постоянки с прямой мощью применяются в начале каждого своего хода.
        static_power = 0
        static_power += sum(1 for cid in p.zone_in_play if cid in {"place_vyaltower", "beast_jellotit"})
        if "place_circus" in p.zone_in_play and p.is_loshara:
            static_power += 2
        if "leg_sexlight" in p.zone_in_play:
            static_power += len(p.death_tokens)
        if static_power:
            p.power_available += static_power
            self.log(f"{p.name}: постоянки дают +{static_power} мощи")
        self.log(f"--- Ход игрока {p.name} ---")

    def _fill_market_resolving(self):
        while len(self.market) < MARKET_SIZE and self.main_deck:
            cid = self.main_deck.pop()
            card = self.cards[cid]
            if card.type == "Беспредел":
                self.log(f"БЕСПРЕДЕЛ на барахолке: {card.full_text}")
                self._resolve_besp(card)
                self.destroyed_besp_pile.append(cid)
                continue
            self.market.append(cid)

    def _fill_legend_market_resolving(self):
        while len(self.legend_market) < LEGEND_MARKET_SIZE and self.legend_deck:
            cid = self.legend_deck.pop()
            card = self.cards[cid]
            if card.type == "Мегабеспредел":
                self.log(f"МЕГАБЕСПРЕДЕЛ на барахолке легенд: {card.full_text}")
                self._resolve_besp(card)
                self.destroyed_besp_pile.append(cid)
                continue
            self.legend_market.append(cid)

    def _resolve_besp(self, card: Card):
        """
        Упрощённая версия: беспределы/мегабеспределы с атакой наносят
        фиксированный урон всем, кто не защитился (авто-пропуск защиты
        для ботов/незаполненных обработчиков). Полная логика произвольного
        текста беспредела появится по мере переноса каждой карты в effects.py.
        """
        handler = None
        from . import effects
        handler = effects.get_effect(card.id)
        if handler:
            handler(self, self.active_player, card)
        else:
            self.log(f"[TODO] Эффект {card.id} ({card.name}) пока не реализован текстово.")

    def play_card(self, player: Player, card_id: str, **kwargs) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if card_id not in player.hand:
            return {"error": "Этой карты нет у вас на руке"}
        if self.pending_attack or self.pending_decision:
            return {"error": "Сначала завершите текущий выбор или атаку"}

        card = self.cards[card_id]
        if player.property_id == "svo_5" and card.postoyanka:
            player.chipsines += 1
            self.log(f"{player.name}: свойство «Постояночка» — +1 чипсина за сыгранную постоянку")
        defer_attack = bool(kwargs.pop("defer_attack", False)) and card.has_attack
        player.hand.remove(card_id)
        player.in_play_this_turn.append(card_id)
        player.power_available += card.power
        if "place_dirty" in player.zone_in_play and "Палочка" in card.name:
            player.power_available += 1
            self.log(f"{player.name}: «Грязная палка» — +1 мощь за Палочку")
        # Значок чипсины в базе обозначает мгновенное получение чипсины.
        # У карт, где чипсина уже описана условием в тексте (например Пейотка),
        # это обрабатывает их отдельный эффект, чтобы не начислять дважды.
        if card.chipsina_symbol and "получи" not in (card.full_text or "").lower():
            player.chipsines += card.chipsina_symbol
            self.log(f"{player.name}: значок чипсины на «{card.name}» — +{card.chipsina_symbol}")

        # Атака не обязана срабатывать в момент розыгрыша: игрок может получить
        # мощь сейчас, а применить её позднее в тот же ход.
        if defer_attack:
            player.available_attacks.append(card_id)
            self.log(f"{player.name}: откладывает атаку карты «{card.name}» до конца хода")

        from . import effects
        handler = effects.get_effect(card_id)
        if handler:
            handler(self, player, card, use_attack=not defer_attack, **kwargs)
        elif card.full_text and card.full_text not in ("(Эффекта нет.)",):
            self.log(f"[TODO] {card.name}: текст «{card.full_text}» пока не реализован, применена только мощь")

        if card.postoyanka and not self.pending_attack:
            player.zone_in_play.append(card_id)
            # Постоянка уходит на стол сразу и больше не участвует в уборке хода.
            player.in_play_this_turn.remove(card_id)
        # Обычная карта остаётся в зоне «сыграно в этом ходу» до end_turn().
        # Именно end_turn() один раз переносит её в сброс. Нельзя класть её
        # в discard здесь, иначе каждая сыгранная карта клонируется.

        return {"ok": True}

    def activate_attack(self, player: Player, card_id: str, **kwargs) -> dict:
        """Применить добровольно отложенную атаку. Мощь второй раз не начисляется."""
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if card_id not in player.available_attacks:
            return {"error": "Эта отложенная атака недоступна"}
        card = self.cards.get(card_id)
        if not card:
            return {"error": "Карта не найдена"}
        player.available_attacks.remove(card_id)
        from . import effects
        handler = effects.get_effect(card_id)
        if handler:
            handler(self, player, card, use_attack=True, attack_only=True, **kwargs)
        else:
            self.log(f"[TODO] Атака «{card.name}» пока не реализована")
        return {"ok": True}

    def apply_card_effect(self, player: Player, card: Card, **kwargs):
        """Применить эффект карты card от лица player, не трогая руку/сброс
        (используется, например, для Шальной магии, разыгрывающей чужую карту)."""
        from . import effects
        handler = effects.get_effect(card.id)
        player.power_available += card.power
        if handler:
            handler(self, player, card, **kwargs)

    def buy_card(self, player: Player, card_id: str) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if self.pending_attack or self.pending_decision:
            return {"error": "Сначала завершите текущий выбор или атаку"}
        if card_id not in self.market and card_id not in self.legend_market:
            return {"error": "Этой карты нет на барахолке"}
        card = self.cards[card_id]
        effective_cost = card.cost
        if player.property_id == "svo_1" and "Сокровище" in card.types_for_matching:
            effective_cost = max(0, effective_cost - 1)
        if card_id in self.legend_market:
            effective_cost = max(0, effective_cost - getattr(player, "legend_discount_turn", 0))
        if effective_cost > player.power_available:
            return {"error": "Не хватает мощи"}
        player.power_available -= effective_cost
        if card_id in self.market:
            self.market.remove(card_id)
            # По правилам пустые ячейки барахолки заполняются в начале следующего хода,
            # а не сразу после каждой покупки.
        else:
            self.legend_market.remove(card_id)
            # То же правило для легендарной барахолки.
        self.receive_card(player, card_id, "hand" if getattr(player, "market_to_hand_turn", False) else "discard")
        self.log(f"{player.name}: покупает {card.name} (-{effective_cost} мощи)")
        return {"ok": True}

    def buy_wild_magic(self, player: Player) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if self.wild_magic_remaining <= 0:
            return {"error": "Шальная магия закончилась"}
        wild_card = next(c for c in self.cards.values() if c.type == WILD_MAGIC_TYPE)
        if wild_card.cost > player.power_available:
            return {"error": "Не хватает мощи"}
        player.power_available -= wild_card.cost
        self.wild_magic_remaining -= 1
        self.receive_card(player, wild_card.id)
        self.log(f"{player.name}: покупает Шальную магию")
        return {"ok": True}

    def buy_familiar(self, player: Player) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if not player.familiar_card_id or player.familiar_bought:
            return {"error": "Нет фамильяра для покупки"}
        card = self.cards[player.familiar_card_id]
        if card.cost > player.power_available:
            return {"error": "Не хватает мощи (нужно 6)"}
        player.power_available -= card.cost
        player.familiar_bought = True
        self.receive_card(player, card.id)
        self.log(f"{player.name}: покупает своего фамильяра {card.name}")
        return {"ok": True}

    def end_turn(self, player: Player) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if self.pending_attack or self.pending_decision:
            return {"error": "Сначала завершите текущий выбор или атаку"}
        player.discard.extend(player.hand)
        player.hand = []
        player.discard.extend(player.in_play_this_turn)
        # постоянки уже перенесены в zone_in_play при розыгрыше, не дублируем
        player.in_play_this_turn = []
        player.power_available = 0
        if player.property_id == "svo_3":
            gained_spells = sum(1 for cid in player.received_this_turn if "Заклинание" in self.cards[cid].types_for_matching)
            if gained_spells:
                player.hand_limit_bonus += gained_spells
                self.log(f"{player.name}: свойство «Заклинание и предел руки» — +{gained_spells} к пределу руки")
        self.draw_cards(player, self.hand_limit(player))

        if self._check_end_condition():
            self._finish_game()
            return {"ok": True, "game_over": True}

        self.turn_idx = (self.turn_idx + 1) % len(self.players)
        while not self.active_player.is_alive():
            self.turn_idx = (self.turn_idx + 1) % len(self.players)
        self.start_turn()
        return {"ok": True}

    def _check_end_condition(self) -> bool:
        if len(self.legend_market) < LEGEND_MARKET_SIZE and not self.legend_deck:
            return True
        if len(self.market) < MARKET_SIZE and not self.main_deck:
            return True
        if not self.undead_token_stack:
            return True
        return False

    # ------------------------------------------------------------------ #
    # Урон / атака / защита
    # ------------------------------------------------------------------ #
    def deal_damage(self, source: Player, target_id: str, amount: int, card_name: str,
                     defendable: bool = True, unavoidable: bool = False) -> bool:
        """Прямой урон одной цели без интерактивной защиты (для быстрых
        сценариев вроде Сырной палочки). Возвращает True, если цель подохла."""
        target = self.get_player(target_id)
        if not target:
            return False
        target.just_died = False
        if "Палочка" in card_name:
            if source.property_id == "svo_10":
                amount += 1
            if "place_dirty" in source.zone_in_play:
                amount += 2
            if "dk_30" in source.death_tokens:
                amount += 4
        target.life -= amount
        self.last_damage_target_id = target_id
        self.log(f"{target.name} отхватывает {amount} урона от «{card_name}» ({source.name})")
        if target.life <= 0:
            self._handle_death(target, killer=source)
            return True
        return False

    def declare_attack(self, source: Player, card: Card, targets, amount: int,
                       unavoidable: bool = False, on_hit: Optional[Callable] = None):
        """Начать атаку. Цели разрешаются по одной, с окном защиты у каждой."""
        target_players = self._resolve_target_group(source, targets)
        self._queue_attack(source, card, target_players, amount, unavoidable, on_hit)

    def attack_target(self, source: Player, card: Card, target_id: str, amount: int,
                      unavoidable: bool = False, on_hit: Optional[Callable] = None):
        target = self.get_player(target_id)
        if target:
            self._queue_attack(source, card, [target], amount, unavoidable, on_hit)

    def _queue_attack(self, source: Player, card: Card, targets: list[Player], amount: int,
                      unavoidable: bool, on_hit: Optional[Callable]):
        if not targets:
            return
        self.pending_attack = {
            "source_id": source.id,
            "card_id": card.id,
            "card_name": card.name,
            "targets": [p.id for p in targets],
            "index": 0,
            "amount": amount,
            "unavoidable": unavoidable,
            "on_hit": on_hit,
        }
        self._advance_attack()

    def _advance_attack(self):
        attack = self.pending_attack
        if not attack:
            return
        if attack["index"] >= len(attack["targets"]):
            self.pending_attack = None
            return
        source = self.get_player(attack["source_id"])
        target = self.get_player(attack["targets"][attack["index"]])
        if not source or not target or not target.is_alive():
            attack["index"] += 1
            self._advance_attack()
            return

        defenses = [cid for cid in target.hand if self.cards[cid].has_defense]
        if defenses and not attack["unavoidable"]:
            options = [{"id": "take", "label": f"Принять {attack['amount']} урона"}]
            options += [
                {"id": f"defend:{cid}", "label": f"Защититься: {self.cards[cid].name}",
                 "detail": self.cards[cid].defense_text or "Сбросить карту и избежать атаки"}
                for cid in defenses
            ]
            def choose_defense(choice: str):
                if choice.startswith("defend:"):
                    cid = choice.split(":", 1)[1]
                    if cid in target.hand:
                        target.hand.remove(cid)
                        target.discard.append(cid)
                        from . import effects
                        effects.apply_defense(self, target, source, self.cards[cid])
                        self.log(f"{target.name}: защищается картой «{self.cards[cid].name}»")
                        attack["index"] += 1
                        self._advance_attack()
                        return
                self._apply_attack_damage(source, target)
            self.request_decision(
                target,
                f"Атака: {attack['card_name']}",
                f"{source.name} атакует тебя на {attack['amount']} урона. Использовать защиту?",
                options,
                choose_defense,
            )
        else:
            self._apply_attack_damage(source, target)

    def _apply_attack_damage(self, source: Player, target: Player):
        attack = self.pending_attack
        if not attack:
            return
        died = self.deal_damage(source, target.id, attack["amount"], attack["card_name"], defendable=False)
        callback = attack.get("on_hit")
        if callback:
            callback(target, died)
        attack["index"] += 1
        self._advance_attack()

    def _resolve_target_group(self, source: Player, targets) -> list[Player]:
        if targets == "all_enemies":
            return self.enemies_of(source)
        if targets == "left_right":
            idx = self.players.index(source)
            left = self.players[(idx - 1) % len(self.players)]
            right = self.players[(idx + 1) % len(self.players)]
            uniq = {left.id: left, right.id: right}
            uniq.pop(source.id, None)
            return list(uniq.values())
        if isinstance(targets, list):
            return [p for p in self.players if p.id in targets]
        return []

    def _handle_death(self, player: Player, killer: Optional[Player]):
        player.just_died = True
        if self.undead_token_stack:
            token_id = self.undead_token_stack.pop()
            player.death_tokens.append(token_id)
            tok_name = self.zhdk.get(token_id, {}).get("name", token_id)
            self.log(f"{player.name} подох и получает ЖДК: {tok_name}")
        player.life = START_LIFE if not player.is_loshara else LOSHARA_MAX_LIFE
        if killer and killer.id != player.id:
            if self.prize_holder:
                old = self.get_player(self.prize_holder)
                if old:
                    old.controls_prize = False
            killer.controls_prize = True
            self.prize_holder = killer.id
            self.log(f"{killer.name} получает главный приз Крутагидона")

    # ------------------------------------------------------------------ #
    # Подсчёт очков
    # ------------------------------------------------------------------ #
    def _finish_game(self):
        self.game_over = True
        scores = {}
        for p in self.players:
            pool = p.zone_in_play + p.hand + p.discard
            vp = 0
            legends = 0
            for cid in pool:
                c = self.cards[cid]
                vp += c.vp
                if c.type == "Легенда":
                    legends += 1
                if c.type == WEAK_STICK_TYPE:
                    vp -= 1
                if p.property_id == "svo_1" and "Сокровище" in c.types_for_matching:
                    vp += 1
            # Условные ПО карт, лежащих у игрока.
            if "beast_geek" in pool:
                vp += sum(1 for cid in pool if "Тварь" in self.cards[cid].types_for_matching)
            if "leg_goose" in pool:
                vp += 2 * legends
            if "place_circus" in pool and p.is_loshara:
                vp += 10  # базовый штраф лошары (-5) становится бонусом (+5)
            if "leg_viagrus" in pool:
                # Вялые палочки перестают быть штрафом: компенсируем уже снятые -1 ПО.
                vp += sum(1 for cid in pool if self.cards[cid].type == WEAK_STICK_TYPE)
            if p.familiar_card_id and p.familiar_bought:
                vp += self.cards[p.familiar_card_id].vp
            if p.is_loshara:
                vp -= 5
            for tid in p.death_tokens:
                tok = self.zhdk.get(tid)
                vp += (tok.get("vp_penalty", -3) if tok else -3)
            scores[p.id] = {"vp": vp, "legends": legends, "death_tokens": len(p.death_tokens)}
        self.logs.append("=== ИГРА ОКОНЧЕНА ===")
        best = max(scores.items(), key=lambda kv: (kv[1]["vp"], kv[1]["legends"], -kv[1]["death_tokens"]))
        self.winner = best[0]
        winner_name = self.get_player(self.winner).name
        self.log(f"Победитель: {winner_name} ({scores[self.winner]['vp']} ПО)")
        self.final_scores = scores

    # ------------------------------------------------------------------ #
    # Сериализация состояния для фронтенда
    # ------------------------------------------------------------------ #
    def to_public_dict(self, viewer_id: Optional[str] = None) -> dict:
        def card_brief(cid):
            c = self.cards[cid]
            return {"id": c.id, "name": c.name, "type": c.type, "cost": c.cost,
                    "power": c.power, "vp": c.vp, "has_attack": c.has_attack,
                    "text": c.full_text, "photo": c.photo}

        players_out = []
        for p in self.players:
            out = {
                "id": p.id, "name": p.name, "avatar": p.avatar, "life": p.life, "max_life": p.max_life,
                "chipsines": p.chipsines, "is_loshara": p.is_loshara,
                "controls_prize": p.controls_prize,
                "power_available": p.power_available,
                "hand_count": len(p.hand),
                "deck_count": len(p.deck), "discard_count": len(p.discard),
                "zone_in_play": [card_brief(c) for c in p.zone_in_play],
                "played_this_turn": [card_brief(c) for c in p.in_play_this_turn],
                "available_attacks": [card_brief(c) for c in p.available_attacks],
                "death_tokens": len(p.death_tokens),
                "property_id": p.property_id,
                "familiar": card_brief(p.familiar_card_id) if p.familiar_card_id else None,
                "familiars": [card_brief(cid) for cid in p.familiar_card_ids],
                "familiar_bought": p.familiar_bought,
            }
            if viewer_id == p.id:
                out["hand"] = [card_brief(c) for c in p.hand]
            players_out.append(out)

        pending_out = None
        if self.pending_decision:
            if viewer_id == self.pending_decision["player_id"]:
                pending_out = {key: value for key, value in self.pending_decision.items() if key != "player_id"}
            else:
                pending_out = {"waiting_for": self.pending_decision["player_name"]}

        return {
            "players": players_out,
            "pending_decision": pending_out,
            "turn_player_id": self.active_player.id,
            "market": [card_brief(c) for c in self.market],
            "legend_market": [card_brief(c) for c in self.legend_market],
            "wild_magic_remaining": self.wild_magic_remaining,
            "vyal_remaining": self.vyal_remaining,
            "main_deck_count": len(self.main_deck),
            "legend_deck_count": len(self.legend_deck),
            "undead_stack_count": len(self.undead_token_stack),
            "game_over": self.game_over,
            "winner": self.winner,
            "logs": self.logs[-30:],
        }
