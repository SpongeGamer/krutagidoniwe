"""
Игровой движок Крутагидона. Не знает про сеть/WebSocket — чистая логика,
чтобы её можно было гонять и тестировать без сервера.
"""
from __future__ import annotations
import json
import os
import random
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable

from .models import (
    Card, load_all_cards, MAIN_DECK_TYPES, LEGEND_DECK_TYPES,
    STARTER_TYPES, WILD_MAGIC_TYPE, WEAK_STICK_TYPE, FAMILIAR_TYPE,
)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..")


def is_stick(card_name: str) -> bool:
    """Это «Палочка»?

    Сравнение без учёта регистра: в базе есть и «Палочка-шлёпалочка»,
    и «Сырная палочка» со строчной буквы. Раньше проверка была
    регистрозависимой, и бонусы «Грязной палки» на половину карт не работали.
    """
    return "палочк" in (card_name or "").lower()


def load_zhdk() -> dict[str, dict]:
    path = os.path.join(_DATA_DIR, "zhdk.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return {r["id"]: r for r in rows}


def load_svo() -> dict[str, dict]:
    path = os.path.join(_DATA_DIR, "svo.json")
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
    no_defense_turn: bool = False
    hand_limit_bonus: int = 0
    bought_familiars: list = field(default_factory=list)  # какие фамильяры уже куплены
    borrowed_cards: list = field(default_factory=list)  # (card_id, владелец) — Шальная магия
    next_attack_unavoidable: bool = False   # «Бензопила»: следующей атаке нельзя помешать
    # Постоянки с атакой (например «Трондец») бьют ОДИН раз за свой ход.
    used_activations: list = field(default_factory=list)
    brotality_active: bool = False          # «Браталити»: убитый не получит жетон ЖДК
    damage_dealt_this_turn: int = 0         # для «Ультимативного тронадо»
    first_damage_bonus_done: bool = False

    just_died: bool = False   # флаг для однократных проверок в этот резолв

    def is_alive(self) -> bool:
        return self.life > 0


class GameState:
    def __init__(self, player_names: list[str], seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.cards: dict[str, Card] = load_all_cards()
        self.zhdk: dict[str, dict] = load_zhdk()
        self.svo: dict[str, dict] = load_svo()
        self.players: list[Player] = [
            Player(id=str(uuid.uuid4())[:8], name=n) for n in player_names
        ]
        self.turn_idx = 0
        self.game_over = False
        self.winner: Optional[str] = None
        self.logs: list[str] = []
        self.last_visual_event: Optional[dict] = None
        self._visual_sequence = 0

        self.main_deck: list[str] = []
        self.market: list[str] = []
        self.legend_deck: list[str] = []
        self.legend_market: list[str] = []
        # Чипсины, лежащие на конкретных картах барахолок после Беспредела.
        self.market_chips: dict[str, int] = {}
        self.wild_magic_remaining = 0
        self.vyal_remaining = 0
        self.destroyed_pile: list[str] = []            # уничтоженные обычные
        self.destroyed_besp_pile: list[str] = []        # уничтоженные беспределы
        # Лента уничтожений: клиент показывает КАЖДУЮ сгоревшую карту
        # картинкой и текстом. Без неё игроки не понимали, что именно пропало.
        self.destroy_reel: list[dict] = []
        self._destroy_seq = 0
        self.undead_token_stack: list[str] = []          # доступные ЖДК
        self.prize_holder: Optional[str] = None
        self.final_scores: dict = {}

        self.pending_attack: Optional[dict] = None
        # Карта Беспредела/Мегабеспредела показана всем до выполнения эффекта.
        self.pending_event: Optional[dict] = None
        self._pending_event_card: Optional[Card] = None
        self._event_sequence = 0
        self.event_queue: list[dict] = []
        self._refilling_markets = False
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

        # ЖДК берём из zhdk.json, но БЕЗ пяти Дохляков (sdk_*): это карты
        # барахолки, они лишь считаются жетонами, а за смерть не выдаются.
        undead_ids = self.death_token_pool()
        self.rng.shuffle(undead_ids)
        self.undead_token_stack = undead_ids[: 4 * len(self.players)] if undead_ids else []

        self.log("Партия подготовлена. Первый ход у " + self.players[0].name)

    def death_token_pool(self) -> list[str]:
        """Жетоны, которые можно получить за смерть.

        Дохляки (sdk_1..sdk_5) сюда не входят: по правилам это карты
        барахолки за 1 чипсину, они лишь СЧИТАЮТСЯ жетонами дохлого колдуна,
        но из стопки смерти не выдаются.
        """
        return [tid for tid in self.zhdk if not tid.startswith("sdk_")]

    def configure_undead_stack(self, count: int):
        """Переопределить число ЖДК перед стартом партии настройкой комнаты."""
        ids = self.death_token_pool()
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

    def emit_visual_event(self, event_type: str, player: Player, card_ids: Optional[list[str]] = None,
                          source: str = "", destination: str = ""):
        """Отдельный факт для клиента: не угадывать по diff, а анимировать действие."""
        self._visual_sequence += 1
        self.last_visual_event = {
            "seq": self._visual_sequence,
            "type": event_type,
            "player_id": player.id,
            "player": player.name,
            "card_ids": card_ids or [],
            "source": source,
            "destination": destination,
        }

    def announce_destroy(self, card_id: str, reason: str = "", victim: Optional[Player] = None):
        """Показать всем, какая карта сгорела: картинка + текст + анимация.

        Нужно Мегабеспределам: раньше карта уничтожалась молча, и игрок видел
        только строчку в журнале, которую вытесняло следующее событие.
        """
        card = self.cards.get(card_id)
        if not card:
            return
        self._destroy_seq += 1
        self.destroy_reel.append({
            "seq": self._destroy_seq,
            "card_id": card_id,
            "name": card.name,
            "type": card.type,
            "text": card.full_text or "",
            "reason": reason,
            "victim": victim.name if victim else "",
            "victim_id": victim.id if victim else "",
        })
        # Держим только последние — старые уже отыграны у всех клиентов.
        self.destroy_reel = self.destroy_reel[-6:]

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

    def set_loshara(self, player: Player, value: bool = True):
        """Единая смена статуса: лошара всегда имеет максимум 15 HP и не может сидеть с 22/15."""
        player.is_loshara = value
        if value:
            player.max_life = LOSHARA_MAX_LIFE
            player.life = min(player.life, LOSHARA_MAX_LIFE)
            self.log(f"{player.name}: становится лошарой (макс. 15 HP)")
        else:
            player.max_life = MAX_LIFE
            player.life = min(player.life, MAX_LIFE)
            self.log(f"{player.name}: снова нормальный колдун")

    def destroy_from_zone(self, player: Player, card_id: str, zone: str,
                          reason: str = "") -> bool:
        cards = getattr(player, zone, None)
        if not isinstance(cards, list) or card_id not in cards:
            return False
        cards.remove(card_id)
        self.destroyed_pile.append(card_id)
        self.log(f"{player.name}: уничтожает «{self.cards[card_id].name}»")
        # Уничтожение видно всем: карта сгорает на экране.
        self.announce_destroy(card_id, reason or f"{player.name} уничтожает карту",
                              victim=player)
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
            # Тасуем несколько раз и отдельным генератором: одиночный shuffle
            # с общим rng давал заметные «слипшиеся» пачки только что купленных карт.
            import random as _r
            shuffler = _r.Random(self.rng.random())
            for _ in range(3):
                shuffler.shuffle(player.deck)
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
        # Значок чипсины в углу карты: выдаётся сразу при получении карты.
        # Раньше он срабатывал только при розыгрыше — покупка чипсину не давала.
        if card.chipsina_symbol:
            player.chipsines += card.chipsina_symbol
            self.log(f"{player.name}: значок чипсины на «{card.name}» — "
                     f"+{card.chipsina_symbol} (всего {player.chipsines})")
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
                self.set_loshara(player, False)
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
                         options: list[dict], callback: Callable, revealed_cards: Optional[list[dict]] = None):
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
            # Раскрытые карты отправляются только игроку, которому адресовано решение.
            "revealed_cards": revealed_cards or [],
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
        self._resume_market_refill()
        return {"ok": True}

    def request_decision_sequence(self, players: list[Player], title: str, text_for_player: Callable,
                                  options_for_player: Callable, apply_choice: Callable, done: Optional[Callable] = None,
                                  cards_for_player: Optional[Callable] = None):
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
            # Игрок должен ВИДЕТЬ карты, о которых его спрашивают.
            revealed = None
            if cards_for_player:
                ids = cards_for_player(current) or []
                revealed = [self.card_public(cid) for cid in ids if cid in self.cards]
            self.request_decision(current, title, text_for_player(current), options, resolve,
                                  revealed_cards=revealed)
        step(0)

    # ------------------------------------------------------------------ #
    # Ход
    # ------------------------------------------------------------------ #
    def start_turn(self):
        for player in self.players:
            player.no_defense_turn = False
        self._refilling_markets = True
        self._resume_market_refill()
        p = self.active_player
        p.power_available = 0
        p.in_play_this_turn = []
        p.available_attacks = []
        p.received_this_turn = []
        p.legend_discount_turn = 0
        p.market_to_hand_turn = False
        # Постоянки с прямой мощью применяются в начале каждого своего хода.
        p.damage_dealt_this_turn = 0
        p.first_damage_bonus_done = False
        p.borrowed_cards = []
        p.next_attack_unavoidable = False
        p.brotality_active = False
        # Новый ход — постоянки-атаки снова доступны.
        p.used_activations = []
        static_power = 0
        static_power += sum(1 for cid in p.zone_in_play if cid in {"place_vyaltower", "beast_jellotit"})
        if "place_circus" in p.zone_in_play and p.is_loshara:
            static_power += 2
        if "leg_sexlight" in p.zone_in_play:
            static_power += len(p.death_tokens)
        if "leg_viagrus" in p.zone_in_play and self.vyal_remaining > 0:
            self.give_weak_sticks(p, 1, "hand")
            self.log(f"{p.name}: Виагрус выдаёт вялую палочку")
        if static_power:
            p.power_available += static_power
            self.log(f"{p.name}: постоянки дают +{static_power} мощи")
        # «Дорогой жетон» (dk_12): в свой ход можно откупиться 5 чипсинами.
        if "dk_12" in p.death_tokens and p.chipsines >= 5:
            def buy_off(choice: str, _p=p):
                if choice == "yes" and _p.chipsines >= 5 and "dk_12" in _p.death_tokens:
                    _p.chipsines -= 5
                    _p.death_tokens.remove("dk_12")
                    self.log(f"{_p.name}: платит 5 чипсин и уничтожает «Дорогой жетон»")
            self.request_decision(
                p, "Дорогой жетон",
                "Потратить 5 чипсин, чтобы избавиться от этого жетона?",
                [{"id": "yes", "label": "Заплатить 5 чипсин"},
                 {"id": "no", "label": "Оставить жетон"}],
                buy_off,
            )
        if p.property_id == "svo_7":
            owned = sum(1 for cid in self.controlled_card_ids(p)
                        if {"Сокровище", "Тварь"} & self.cards[cid].types_for_matching)
            if owned >= 2:
                p.chipsines += 1
                self.log(f"{p.name}: свойство «Твари с сокровищами» — +1 чипсина")
        if p.property_id == "svo_4":
            owned = sum(1 for cid in self.controlled_card_ids(p)
                        if {"Волшебник", "Заклинание"} & self.cards[cid].types_for_matching)
            if owned >= 2:
                self._offer_enemy_top_card(p)
        self.log(f"--- Ход игрока {p.name} ---")

    def _offer_enemy_top_card(self, player: Player):
        """Свойство «Контроль врага»: сыграть верхнюю карту колоды врага."""
        enemies = [e for e in self.enemies_of(player) if e.is_alive()]
        if not enemies:
            return
        options = [{"id": e.id, "label": e.name} for e in enemies]
        options.append({"id": "skip", "label": "Пропустить"})

        def resolve(choice: str):
            if choice == "skip":
                return
            target = self.get_player(choice)
            if not target:
                return
            if not target.deck:
                self.reshuffle_discard_into_deck(target)
            if not target.deck:
                return
            top_id = target.deck.pop()
            top = self.cards[top_id]
            self.log(f"{player.name}: свойство «Контроль врага» — играет «{top.name}» из колоды {target.name}")
            self.apply_card_effect(player, top)
            target.discard.append(top_id)

        self.request_decision(
            player, "Контроль врага",
            "Сыграть верхнюю карту колоды выбранного врага?", options, resolve,
        )

    def _resume_market_refill(self):
        """Продолжить начало хода только когда предыдущий Беспредел полностью разрешён."""
        if not self._refilling_markets or self.pending_event or self.pending_decision or self.pending_attack:
            return
        self._fill_market_resolving()
        if self.pending_event or self.pending_decision or self.pending_attack:
            return
        self._fill_legend_market_resolving()
        if not (self.pending_event or self.pending_decision or self.pending_attack):
            self._refilling_markets = False

    def _queue_event(self, card: Card):
        self._event_sequence = getattr(self, "_event_sequence", 0) + 1
        self.pending_event = {
            "id": card.id,
            "name": card.name,
            "type": card.type,
            "text": card.full_text,
            "seq": self._event_sequence,
        }
        self._pending_event_card = card
        self.log(f"{card.type.upper()} показан: {card.full_text}")

    def resolve_event(self) -> dict:
        if not self.pending_event:
            # Обычно это второй клик по кнопке или запоздавший клик,
            # когда событие уже закрыл бот. Молча игнорируем.
            return {"ok": True}
        # Показ жетона ЖДК — просто информационное окно, карты за ним нет.
        if not self._pending_event_card:
            self.pending_event = None
            if self.event_queue:                 # показываем следующий жетон
                self.pending_event = self.event_queue.pop(0)
                return {"ok": True}
            self._resume_market_refill()
            return {"ok": True}
        card = self._pending_event_card
        self.pending_event = None
        self._pending_event_card = None
        self._resolve_besp(card)
        if not self.pending_event and self.event_queue:
            self.pending_event = self.event_queue.pop(0)
            return {"ok": True}
        self._resume_market_refill()
        return {"ok": True}

    def _fill_market_resolving(self):
        while len(self.market) < MARKET_SIZE and self.main_deck:
            cid = self.main_deck.pop()
            card = self.cards[cid]
            if card.type == "Беспредел":
                self.destroyed_besp_pile.append(cid)
                self._queue_event(card)
                return
            self.market.append(cid)

    def _fill_legend_market_resolving(self):
        while len(self.legend_market) < LEGEND_MARKET_SIZE and self.legend_deck:
            cid = self.legend_deck.pop()
            card = self.cards[cid]
            if card.type == "Мегабеспредел":
                self.destroyed_besp_pile.append(cid)
                self._queue_event(card)
                return
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
        elif card.id not in effects.ACTIVATION_REGISTRY:
            self.log(f"[TODO] Эффект {card.id} ({card.name}) пока не реализован текстово.")

    def play_card(self, player: Player, card_id: str, **kwargs) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if card_id not in player.hand:
            return {"error": "Этой карты нет у вас на руке"}
        if self.pending_event or self.pending_attack or self.pending_decision:
            return {"error": "Сначала завершите текущий выбор или атаку"}

        card = self.cards[card_id]
        if player.property_id == "svo_5" and card.postoyanka:
            player.chipsines += 1
            self.log(f"{player.name}: свойство «Постояночка» — +1 чипсина за сыгранную постоянку")
        defer_attack = bool(kwargs.pop("defer_attack", False)) and card.has_attack
        player.hand.remove(card_id)
        player.in_play_this_turn.append(card_id)
        player.power_available += card.power
        if card.power:
            self.log(f"{player.name}: «{card.name}» +{card.power} мощи (всего {player.power_available})")
        if "place_dirty" in player.zone_in_play and is_stick(card.name):
            player.power_available += 1
            self.log(f"{player.name}: «Грязная палка» — +1 мощь за Палочку")
        # «Виагрус»: всякий раз, когда играешь вялую палочку, +3 мощи.
        if card.type == WEAK_STICK_TYPE and "leg_viagrus" in player.zone_in_play:
            player.power_available += 3
            self.log(f"{player.name}: «Виагрус» — +3 мощи за вялую палочку "
                     f"(всего {player.power_available})")
        # Значок чипсины в базе обозначает мгновенное получение чипсины.
        # У карт, где чипсина уже описана условием в тексте (например Пейотка),
        # это обрабатывает их отдельный эффект, чтобы не начислять дважды.
        # Значок чипсины уже выдан при получении карты (см. receive_card).

        # Атака не обязана срабатывать в момент розыгрыша: игрок может получить
        # мощь сейчас, а применить её позднее в тот же ход.
        if defer_attack:
            player.available_attacks.append(card_id)
            self.log(f"{player.name}: откладывает атаку карты «{card.name}» до конца хода")

        from . import effects
        handler = effects.get_effect(card_id)
        if handler:
            handler(self, player, card, use_attack=not defer_attack, **kwargs)
        elif card.id in effects.ACTIVATION_REGISTRY:
            # Постоянка с активируемым эффектом: сработает по кнопке на столе.
            self.log(f"{player.name}: «{card.name}» — постоянка, эффект активируется кнопкой")
        elif card.full_text and card.full_text not in ("(Эффекта нет.)",):
            self.log(f"[TODO] {card.name}: текст «{card.full_text}» пока не реализован, применена только мощь")

        if card.postoyanka and not self.pending_attack:
            player.zone_in_play.append(card_id)
            # Постоянка уходит на стол сразу и больше не участвует в уборке хода.
            player.in_play_this_turn.remove(card_id)
        # Обычная карта остаётся в зоне «сыграно в этом ходу» до end_turn().
        # Именно end_turn() один раз переносит её в сброс. Нельзя класть её
        # в discard здесь, иначе каждая сыгранная карта клонируется.

        self.emit_visual_event("play", player, [card_id], "hand", "permanent" if card.postoyanka else "table")
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
        elif card.id not in effects.ACTIVATION_REGISTRY:
            self.log(f"[TODO] Атака «{card.name}» пока не реализована")
        return {"ok": True}

    # Постоянки, которые бьют раз за ход, а не уничтожаются при активации.
    ONCE_PER_TURN_ACTIVATIONS = {"leg_throne"}

    def activate_permanent(self, player: Player, card_id: str, **kwargs) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if card_id not in player.zone_in_play:
            return {"error": "Эта постоянка не находится у вас на столе"}
        # «Трондец» — это АТАКА, а атака у карты одна за ход.
        # Без этого его можно было жать бесконечно и убить любого за один ход.
        if card_id in self.ONCE_PER_TURN_ACTIVATIONS:
            if card_id in player.used_activations:
                return {"error": f"«{self.cards[card_id].name}» уже атаковал в этом ходу"}
            player.used_activations.append(card_id)
        from . import effects
        return effects.apply_activation(self, player, self.cards[card_id], **kwargs)

    def apply_card_effect(self, player: Player, card: Card, add_power: bool = True, **kwargs):
        """Применить эффект карты card от лица player, не трогая руку/сброс
        (используется, например, для Шальной магии, разыгрывающей чужую карту).

        add_power=False, если мощь уже начислена вызывающей стороной:
        Шальная магия начисляла её дважды (украл карту на 3 мощи — получил 6).
        """
        from . import effects
        handler = effects.get_effect(card.id)
        if add_power:
            player.power_available += card.power
        if handler:
            handler(self, player, card, **kwargs)

    # Карты, которые бьют по площади или выбирают цель сами внутри эффекта.
    NO_TARGET_CARDS = {"leg_minigun", "leg_necrorot", "fam_weaboo", "leg_hemor",
                       "leg_rabbit", "leg_shitcher", "beast_kinky",
                       "spell_dirtwind", "wiz_bandits", "wiz_sosok"}

    def card_needs_target(self, card: Card) -> bool:
        """Нужна ли карте одна конкретная цель.

        Карты «каждому врагу» и Беспределы бьют по площади — спрашивать
        цель у них нельзя, иначе игрок получит бессмысленное окно.
        """
        if card.id in self.NO_TARGET_CARDS:
            return False
        if card.type in ("Беспредел", "Мегабеспредел"):
            return False
        text = f"{card.attack_text or ''} {card.full_text or ''}".lower()
        if re.search(r"кажд(ый|ому|ого|ые)\s+(колдун|враг)|всех врагов|все враги", text):
            return False
        return bool(re.search(r"выбранн|выбери|левому|правому|левого|правого", text))

    def choose_enemy(self, player: Player, card: Card, callback: Callable,
                     text: Optional[str] = None, allow_skip: bool = False):
        """Спросить игрока, на кого направить эффект карты.

        Окно показывается ВСЕГДА, даже когда враг остался один: игрок должен
        видеть, кого он выбирает, а не гадать, сработала карта или нет.
        """
        enemies = [e for e in self.enemies_of(player) if e.is_alive()]
        if not enemies:
            self.log(f"«{card.name}»: живых врагов нет — выбирать некого")
            return
        options = [{"id": e.id, "label": e.name,
                    "detail": f"♥ {e.life}/{e.max_life} · ЖДК {len(e.death_tokens)}"}
                   for e in enemies]
        if allow_skip:
            options.append({"id": "skip", "label": "Пропустить"})

        def resolve(choice: str):
            if choice == "skip":
                return
            target = self.get_player(choice)
            if target:
                callback(target)

        self.request_decision(player, card.name, text or "Выбери врага",
                              options, resolve,
                              revealed_cards=[self.card_public(card.id)])

    def play_foreign_card(self, player: Player, card: Card, **kwargs):
        """Разыграть чужую карту ПОЛНОСТЬЮ: и мощь, и атака с выбором цели.

        Шальная магия и Капитан Бартоломяу раньше применяли эффект «как есть»:
        карта с атакой просто давала мощь, потому что цель никто не спрашивал.
        """
        if kwargs.get("target_id") or not card.has_attack or not self.card_needs_target(card):
            self.apply_card_effect(player, card, add_power=False, **kwargs)
            return
        enemies = [e for e in self.enemies_of(player) if e.is_alive()]
        if not enemies:
            self.apply_card_effect(player, card, add_power=False, **kwargs)
            return
        options = [{"id": e.id, "label": e.name,
                    "detail": f"♥ {e.life}/{e.max_life} · ЖДК {len(e.death_tokens)}"}
                   for e in enemies]

        def choose(target_id: str):
            # kwargs может уже содержать target_id/target_ids (например от бота).
            # Выбор игрока главнее — перетираем, а не передаём дважды.
            params = dict(kwargs)
            params["target_id"] = target_id
            params["target_ids"] = [e.id for e in enemies]
            self.apply_card_effect(player, card, add_power=False, **params)

        self.request_decision(
            player, card.name,
            f"«{card.name}» — атака. Выбери цель.",
            options, choose, revealed_cards=[self.card_public(card.id)],
        )

    def buy_card(self, player: Player, card_id: str, use_chipsines: Optional[int] = None) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if self.pending_event or self.pending_attack or self.pending_decision:
            return {"error": "Сначала завершите текущий выбор или атаку"}
        if card_id not in self.market and card_id not in self.legend_market:
            return {"error": "Этой карты нет на барахолке"}
        card = self.cards[card_id]
        effective_cost = card.cost
        if player.property_id == "svo_1" and "Сокровище" in card.types_for_matching:
            effective_cost = max(0, effective_cost - 1)
        if card_id in self.legend_market:
            effective_cost = max(0, effective_cost - getattr(player, "legend_discount_turn", 0))
        # Чипсинами доплачивают ТОЛЬКО за легенды и фамильяров.
        # Обычные карты барахолки покупаются исключительно за мощь.
        chips_allowed = card_id in self.legend_market or "Легенда" in card.types_for_matching
        if not chips_allowed:
            if effective_cost > player.power_available:
                return {"error": "За эту карту чипсинами платить нельзя — не хватает мощи"}
            from_chips = 0
        else:
            if effective_cost > player.power_available + player.chipsines:
                return {"error": "Не хватает мощи и чипсин"}
            if use_chipsines is None:
                from_chips = max(0, effective_cost - player.power_available)
            else:
                from_chips = max(0, min(int(use_chipsines), effective_cost, player.chipsines))
        from_power = effective_cost - from_chips
        if from_power > player.power_available:
            return {"error": "Не хватает мощи при таком раскладе"}
        player.power_available -= from_power
        if from_chips:
            player.chipsines -= from_chips
            self.log(f"{player.name}: платит {from_power} мощи + {from_chips} чипсин(ы) "
                     f"за «{card.name}»")
        market_chip_bonus = self.market_chips.pop(card_id, 0)
        if card_id in self.market:
            self.market.remove(card_id)
            # По правилам пустые ячейки барахолки заполняются в начале следующего хода.
        else:
            self.legend_market.remove(card_id)
        self.receive_card(player, card_id, "hand" if getattr(player, "market_to_hand_turn", False) else "discard")
        if market_chip_bonus:
            player.chipsines += market_chip_bonus
            self.log(f"{player.name}: получает {market_chip_bonus} чипсин(ы) с барахолки")
        self.log(f"{player.name}: покупает {card.name} (-{effective_cost} мощи)")
        self.emit_visual_event("buy", player, [card_id], "market", "discard")
        return {"ok": True}

    def buy_wild_magic(self, player: Player) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if self.wild_magic_remaining <= 0:
            return {"error": "Шальная магия закончилась"}
        wild_card = next(c for c in self.cards.values() if c.type == WILD_MAGIC_TYPE)
        # За Шальную магию чипсинами платить нельзя — только мощь.
        if wild_card.cost > player.power_available:
            return {"error": "За Шальную магию чипсинами платить нельзя — не хватает мощи"}
        player.power_available -= wild_card.cost
        self.wild_magic_remaining -= 1
        self.receive_card(player, wild_card.id)
        self.log(f"{player.name}: покупает Шальную магию за {wild_card.cost} мощи "
                 f"(осталось {player.power_available})")
        # Без этого покупка выглядела так, будто ничего не произошло.
        self.emit_visual_event("buy", player, [wild_card.id], "market", "discard")
        return {"ok": True}

    def buy_familiar(self, player: Player, card_id: Optional[str] = None,
                      use_chipsines: Optional[int] = None) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        available = [c for c in (player.familiar_card_ids or [])
                     if c not in player.bought_familiars]
        if not available and player.familiar_card_id and not player.familiar_bought:
            available = [player.familiar_card_id]
        if not available:
            return {"error": "Все твои фамильяры уже куплены"}
        # Свойство «Фамильяры» даёт три карты — какую покупать, решает игрок.
        chosen_id = card_id if card_id in available else available[0]
        card = self.cards[chosen_id]
        if card.cost > player.power_available + player.chipsines:
            return {"error": "Не хватает мощи и чипсин (нужно 6)"}
        if use_chipsines is None:
            from_chips = max(0, card.cost - player.power_available)
        else:
            from_chips = max(0, min(int(use_chipsines), card.cost, player.chipsines))
        from_power = card.cost - from_chips
        if from_power > player.power_available:
            return {"error": "Не хватает мощи при таком раскладе"}
        player.power_available -= from_power
        if from_chips:
            player.chipsines -= from_chips
            self.log(f"{player.name}: платит {from_power} мощи + {from_chips} чипсин(ы) за фамильяра")
        player.bought_familiars.append(chosen_id)
        player.familiar_bought = True
        self.receive_card(player, card.id)
        self.log(f"{player.name}: покупает фамильяра «{card.name}» за {card.cost} мощи "
                 f"(осталось {player.power_available})")
        self.emit_visual_event("buy", player, [card.id], "market", "discard")
        return {"ok": True}

    def end_turn(self, player: Player) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if self.pending_event or self.pending_attack or self.pending_decision:
            return {"error": "Сначала завершите текущий выбор или атаку"}
        # Владелец Главного приза получает чипсину в конце своего хода.
        if player.controls_prize:
            player.chipsines += 1
            self.log(f"{player.name}: Главный приз приносит 1 чипсину "
                     f"(всего {player.chipsines})")
        player.discard.extend(player.hand)
        player.hand = []
        # Карты, украденные Шальной магией, возвращаются владельцу в его сброс.
        borrowed = {cid: owner for cid, owner in player.borrowed_cards}
        player.borrowed_cards = []
        played_cards = [c for c in player.in_play_this_turn if c not in borrowed]
        for cid, owner_id in borrowed.items():
            owner = self.get_player(owner_id)
            if owner:
                owner.discard.append(cid)
                self.log(f"«{self.cards[cid].name}» возвращается в сброс {owner.name}")
            else:
                player.discard.append(cid)
        player.discard.extend(played_cards)
        # постоянки уже перенесены в zone_in_play при розыгрыше, не дублируем
        player.in_play_this_turn = []
        if played_cards:
            self.emit_visual_event("discard", player, played_cards, "table", "discard")
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
        if is_stick(card_name):
            if source.property_id == "svo_10":
                amount += 1
            if "place_dirty" in source.zone_in_play:
                amount += 2
            if "dk_30" in source.death_tokens:
                amount += 4
        if "leg_arena" in source.zone_in_play and source is not target:
            amount *= 2
            self.log(f"{source.name}: Чипсихоз-арена удваивает урон до {amount}")
        target.life -= amount
        if source is not target and amount > 0:
            source.damage_dealt_this_turn += amount
            if "leg_park" in source.zone_in_play:
                self.heal(source, amount)
            if "leg_tronado" in source.zone_in_play and not source.first_damage_bonus_done:
                source.first_damage_bonus_done = True
                source.power_available += amount
                self.log(f"{source.name}: Ультимативное тронадо даёт +{amount} мощи")
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

    def declare_variable_attack(self, source: Player, card: Card, targets_with_damage: list[tuple[Player, int]],
                                unavoidable: bool = False, on_hit: Optional[Callable] = None):
        """Одна атака, но у каждой цели свой урон. Защита запрашивается по очереди."""
        self._queue_attack(source, card, targets_with_damage, None, unavoidable, on_hit)

    def _queue_attack(self, source: Player, card: Card, targets, amount: Optional[int],
                      unavoidable: bool, on_hit: Optional[Callable],
                      no_redirect: bool = False):
        if not targets:
            return
        entries = []
        for target in targets:
            if isinstance(target, tuple):
                player, target_amount = target
            else:
                player, target_amount = target, amount
            entries.append({"id": player.id, "amount": target_amount})
        if getattr(source, "next_attack_unavoidable", False):
            unavoidable = True
            source.next_attack_unavoidable = False
            self.log(f"{source.name}: этой атаки нельзя избежать")
        # Часть карт прямо запрещает разворот атаки («Хахатальер Злорадник»).
        text = f"{card.attack_text or ''} {card.full_text or ''}".lower()
        if "нельзя перенаправить" in text:
            no_redirect = True
        self.pending_attack = {
            "source_id": source.id,
            "card_id": card.id,
            "card_name": card.name,
            "targets": entries,
            "index": 0,
            "unavoidable": unavoidable,
            "on_hit": on_hit,
            "no_redirect": no_redirect,
        }
        self._advance_attack()

    def _advance_attack(self):
        attack = self.pending_attack
        if not attack:
            return
        if attack["index"] >= len(attack["targets"]):
            self.pending_attack = None
            self._resume_market_refill()
            return
        source = self.get_player(attack["source_id"])
        target_entry = attack["targets"][attack["index"]]
        target = self.get_player(target_entry["id"])
        amount = target_entry["amount"]
        if not source or not target or not target.is_alive():
            attack["index"] += 1
            self._advance_attack()
            return

        # У «Баклажабы» флаг защиты стоит ошибочно: в тексте только активация.
        NOT_DEFENSES = {"beast_jaba"}
        defenses = [] if target.no_defense_turn else [
            cid for cid in target.hand
            if self.cards[cid].has_defense and cid not in NOT_DEFENSES
            and (self.cards[cid].defense_text or "").strip()
        ]
        if defenses and not attack["unavoidable"]:
            options = [{"id": "take", "label": f"Принять {amount} урона"}]
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
                        self.log(f"{target.name}: защищается картой «{self.cards[cid].name}» — "
                                 f"{self.cards[cid].defense_text or 'атака отменена'}")
                        self.emit_visual_event("defend", target, [cid], "hand", "discard")
                        attack["index"] += 1
                        self._advance_attack()
                        return
                self._apply_attack_damage(source, target)
            card_obj = self.cards.get(attack.get("card_id"))
            is_besp = bool(card_obj and card_obj.type in ("Беспредел", "Мегабеспредел"))
            if is_besp:
                title = f"{attack['card_name']} бьёт!"
                text = f"Беспредел наносит тебе {amount} урона. Использовать защиту?"
            else:
                title = f"Атака: {attack['card_name']}"
                text = f"{source.name} атакует тебя на {amount} урона. Использовать защиту?"
            self.request_decision(target, title, text, options, choose_defense)
        else:
            self._apply_attack_damage(source, target)

    def _apply_attack_damage(self, source: Player, target: Player):
        attack = self.pending_attack
        if not attack:
            return
        amount = attack["targets"][attack["index"]]["amount"]
        died = self.deal_damage(source, target.id, amount, attack["card_name"], defendable=False)
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

    def _resolve_death_token(self, player: Player, token_id: str, killer: Optional[Player]):
        """Немедленные эффекты ЖДК. Сложные многоигроковые выборы добавляются отдельно."""
        if token_id == "dk_1":
            self.deal_damage(player, player.id, 4 * sum(1 for cid in player.discard if "Легенда" in self.cards[cid].types_for_matching), "Урон за легенд", defendable=False)
        elif token_id == "dk_2":
            player.chipsines -= (player.chipsines + 1) // 2
        elif token_id == "dk_3" and killer:
            killer.chipsines += 2
        elif token_id == "dk_4":
            self.set_loshara(player, True)
        elif token_id == "dk_9":
            legends = [cid for cid in player.hand if "Легенда" in self.cards[cid].types_for_matching]
            for cid in legends:
                player.hand.remove(cid)
                player.deck.append(cid)
            self.rng.shuffle(player.deck)
        elif token_id == "dk_11":
            self.give_weak_sticks(player, sum(1 for cid in player.discard if "Легенда" in self.cards[cid].types_for_matching), "hand")
        elif token_id == "dk_15":
            self.give_weak_sticks(player, 2, "deck_bottom")
        elif token_id == "dk_17":
            if self.main_deck and self.cards[self.main_deck[-1]].type == "Беспредел" and self.undead_token_stack:
                player.death_tokens.append(self.undead_token_stack.pop())
        elif token_id == "dk_18":
            player.chipsines += 1
        elif token_id == "dk_19":
            for enemy in self.enemies_of(player):
                enemy.chipsines += 1
        elif token_id == "dk_20":
            if player.is_loshara:
                if self.undead_token_stack:
                    player.death_tokens.append(self.undead_token_stack.pop())
            else:
                self.set_loshara(player, True)
        elif token_id == "dk_22":
            self.deal_damage(player, player.id, player.chipsines, "Чипсовый опиздюлин", defendable=False)
        elif token_id == "dk_23":
            player.deck.extend(player.zone_in_play)
            player.zone_in_play = []
            self.rng.shuffle(player.deck)
        elif token_id == "dk_25":
            if player.deck and "Легенда" in self.cards[player.deck[-1]].types_for_matching and self.undead_token_stack:
                player.death_tokens.append(self.undead_token_stack.pop())
        elif token_id == "dk_26":
            if player.hand:
                amount = max(self.cards[cid].cost for cid in player.hand)
                self.deal_damage(player, player.id, amount, "Не бей себя!", defendable=False)
        elif token_id == "dk_28":
            self.set_loshara(player, not player.is_loshara)
        elif token_id == "dk_29":
            self.give_weak_sticks(player, 1, "deck_top")
        elif token_id == "dk_5":
            # Выбери врага: он получает случайную карту из твоей стопки сброса.
            enemies = [e for e in self.enemies_of(player) if e.is_alive()]
            if enemies and player.discard:
                options = [{"id": e.id, "label": e.name} for e in enemies]

                def give(choice: str):
                    target = self.get_player(choice)
                    if not target or not player.discard:
                        return
                    cid = self.rng.choice(player.discard)
                    player.discard.remove(cid)
                    target.discard.append(cid)
                    self.log(f"{target.name}: получает «{self.cards[cid].name}» из сброса {player.name}")

                self.request_decision(player, "Сдача сброса",
                                      "Кому подкинуть карту из своего сброса?", options, give)
        elif token_id == "dk_6":
            # Если тебя убил лошара — он может стать нормальным.
            if killer and killer.is_loshara:
                options = [{"id": "yes", "label": "Стать нормальным"},
                           {"id": "no", "label": "Остаться лошарой"}]

                def unlose(choice: str):
                    if choice == "yes":
                        self.set_loshara(killer, False)

                self.request_decision(killer, "Разлошаривание",
                                      f"Ты убил {player.name} и можешь перестать быть лошарой",
                                      options, unlose)
        elif token_id == "dk_7":
            # Каждый враг МОЖЕТ передать тебе Знак с руки или из сброса.
            enemies = [e for e in self.enemies_of(player) if e.is_alive()]

            def opts_for(enemy):
                has = "start_znak" in enemy.hand or "start_znak" in enemy.discard
                base = [{"id": "no", "label": "Не отдавать"}]
                return ([{"id": "give", "label": "Отдать Знак"}] + base) if has else base

            def apply_choice(enemy, choice):
                if choice != "give":
                    return
                for zone in (enemy.hand, enemy.discard):
                    if "start_znak" in zone:
                        zone.remove("start_znak")
                        player.hand.append("start_znak")
                        self.log(f"{enemy.name}: отдаёт Знак игроку {player.name}")
                        return

            if enemies:
                self.request_decision_sequence(
                    enemies, "Раздача знаков на спавне",
                    lambda e: f"Отдать Знак игроку {player.name}?",
                    opts_for, apply_choice)
        elif token_id == "dk_10":
            # После воскрешения поменяйся жизнями с любым другим колдуном.
            others = [o for o in self.players if o.id != player.id and o.is_alive()]
            if others:
                options = [{"id": o.id, "label": f"{o.name} ({o.life} HP)"} for o in others]

                def swap(choice: str):
                    other = self.get_player(choice)
                    if not other:
                        return
                    player.life, other.life = other.life, player.life
                    player.life = min(player.life, player.max_life)
                    other.life = min(other.life, other.max_life)
                    self.log(f"{player.name} и {other.name} обменялись жизнями")

                self.request_decision(player, "Жизненный обмен",
                                      "С кем поменяться жизнями?", options, swap)
        elif token_id == "dk_24":
            # Раскрой верхнюю карту своей колоды. Можешь её уничтожить.
            if not player.deck:
                self.reshuffle_discard_into_deck(player)
            if player.deck:
                top_id = player.deck[-1]
                top = self.cards[top_id]
                options = [{"id": "kill", "label": f"Уничтожить «{top.name}»"},
                           {"id": "keep", "label": "Оставить в колоде"}]

                def choose(choice: str):
                    if choice == "kill" and player.deck and player.deck[-1] == top_id:
                        player.deck.pop()
                        self.destroyed_pile.append(top_id)
                        self.log(f"{player.name}: уничтожает «{top.name}»")

                self.request_decision(player, "Халява!", f"Верхняя карта: {top.name}",
                                      options, choose,
                                      revealed_cards=[self.card_public(top_id)])
        elif token_id == "dk_27":
            # Каждый враг МОЖЕТ показать средний палец: сбрось 1 карту за каждого.
            enemies = [e for e in self.enemies_of(player) if e.is_alive()]

            def finger_opts(enemy):
                return [{"id": "yes", "label": "Показать средний палец"},
                        {"id": "no", "label": "Воздержаться"}]

            def finger_apply(enemy, choice):
                if choice != "yes" or not player.hand:
                    return
                cid = self.rng.choice(player.hand)
                player.hand.remove(cid)
                player.discard.append(cid)
                self.log(f"{enemy.name} показывает палец — {player.name} сбрасывает «{self.cards[cid].name}»")

            if enemies:
                self.request_decision_sequence(
                    enemies, "Пошел ты!",
                    lambda e: f"Показать средний палец игроку {player.name}?",
                    finger_opts, finger_apply)

    def _handle_death(self, player: Player, killer: Optional[Player]):
        player.just_died = True
        token_id = None
        # «Браталити»: убитый в этот раз не получает жетон дохлого колдуна.
        if killer and getattr(killer, "brotality_active", False):
            killer.brotality_active = False
            self.log(f"{player.name} подох, но «Браталити» избавляет его от жетона")
            player.life = START_LIFE if not player.is_loshara else LOSHARA_MAX_LIFE
            if killer.id != player.id:
                if self.prize_holder:
                    old_holder = self.get_player(self.prize_holder)
                    if old_holder:
                        old_holder.controls_prize = False
                killer.controls_prize = True
                self.prize_holder = killer.id
                self.log(f"{killer.name} получает главный приз Крутагидона")
            return
        if self.undead_token_stack:
            token_id = self.undead_token_stack.pop()
            player.death_tokens.append(token_id)
            tok = self.zhdk.get(token_id, {})
            tok_name = tok.get("name", token_id)
            tok_text = tok.get("effect_text", "")
            self.log(f"{player.name} получает жетон дохлого колдуна: «{tok_name}». {tok_text}")
            # Показываем жетон крупно: игрок должен видеть, что именно ему выпало.
            self._event_sequence = getattr(self, "_event_sequence", 0) + 1
            token_event = {
                "id": token_id,
                "name": tok_name,
                "seq": self._event_sequence,
                "type": "Жетон дохлого колдуна",
                "text": tok_text,
                "owner_id": player.id,
                "owner": player.name,
            }
            if self.pending_event:
                # Окно уже занято (умер кто-то ещё) — встаём в очередь,
                # иначе второй жетон никто не увидит.
                self.event_queue.append(token_event)
            else:
                self.pending_event = token_event
                self._pending_event_card = None
        player.life = START_LIFE if not player.is_loshara else LOSHARA_MAX_LIFE
        if token_id:
            self._resolve_death_token(player, token_id, killer)
            # Любой жетон не должен оставлять игрока выше нового максимума HP.
            player.life = min(player.life, player.max_life)
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
            # В конце игры считается ВСЯ колода игрока, включая непросмотренную
            # часть deck — иначе половина купленных карт просто не учитывалась.
            pool = p.zone_in_play + p.hand + p.discard + p.deck
            vp = 0
            legends = 0
            # Разбивка по статьям — из неё строится «подсчёт вживую» в конце партии.
            steps: list[dict] = []

            def add_step(label: str, delta: int, kind: str = "plain"):
                if delta:
                    steps.append({"label": label, "delta": delta, "kind": kind})

            cards_vp = 0
            sticks_vp = 0
            treasure_vp = 0
            for cid in pool:
                c = self.cards[cid]
                vp += c.vp
                cards_vp += c.vp
                if c.type == "Легенда":
                    legends += 1
                if c.type == WEAK_STICK_TYPE:
                    vp -= 1
                    sticks_vp -= 1
                if p.property_id == "svo_1" and "Сокровище" in c.types_for_matching:
                    vp += 1
                    treasure_vp += 1
            add_step(f"Очки на картах ({len(pool)} шт.)", cards_vp, "cards")
            add_step("Вялые палочки", sticks_vp, "bad")
            add_step("Свойство «Скидка на сокровища»", treasure_vp, "good")
            # Условные ПО карт, лежащих у игрока.
            geeks = pool.count("beast_geek")
            if geeks:
                # Каждая копия Гикпига считает тварей отдельно — они стакаются.
                _b = sum(1 for cid in pool if "Тварь" in self.cards[cid].types_for_matching) * geeks
                label = "Потный Гикпиг: за тварей" if geeks == 1 else f"Потный Гикпиг x{geeks}: за тварей"
                vp += _b
                add_step(label, _b, "good")
            geese = pool.count("leg_goose")
            if geese:
                _gv = 2 * legends * geese
                label = "Гусыня: за легенды" if geese == 1 else f"Гусыня x{geese}: за легенды"
                vp += _gv
                add_step(label, _gv, "good")
            if "place_circus" in pool and p.is_loshara:
                vp += 10  # базовый штраф лошары (-5) становится бонусом (+5)
                add_step("Цирк Лошашных: штраф стал бонусом", 10, "good")
            if "leg_viagrus" in pool:
                # «Твои вялые палочки приносят тебе ПО, а не отнимают их»:
                # снимаем уже вычтенный -1 и начисляем +1 сверху.
                _v = sum(1 for cid in pool if self.cards[cid].type == WEAK_STICK_TYPE)
                vp += _v * 2
                add_step("Виагрус: палочки приносят ПО", _v * 2, "good")
            # Купленные фамильяры уже лежат в колоде/сбросе игрока, поэтому их
            # ПО посчитаны выше в «Очках на картах». Отдельной строкой их
            # добавлять НЕЛЬЗЯ — получался двойной счёт. Здесь только показываем
            # игроку, за каких именно фамильяров ему начислено (свойство
            # «Фамильяры» даёт до трёх, и все должны быть видны в разбивке).
            bought_fams = [cid for cid in (p.bought_familiars or []) if cid in pool]
            if not bought_fams and p.familiar_bought and p.familiar_card_id in pool:
                bought_fams = [p.familiar_card_id]
            for fid in bought_fams:
                fam = self.cards[fid]
                if fam.vp:
                    steps.append({"label": f"↳ в том числе фамильяр «{fam.name}»",
                                  "delta": 0, "kind": "note",
                                  "note": f"+{fam.vp} ПО уже учтены в картах"})
            # Главный приз Крутагидона даёт +5 ПО владельцу.
            # Жетон «Неглавный приз» (dk_8) этот бонус отменяет.
            if p.controls_prize and "dk_8" not in p.death_tokens:
                vp += 5
                add_step("Главный приз Крутагидона", 5, "prize")
            if p.is_loshara:
                vp -= 5
                add_step("Ты лошара", -5, "bad")
            for tid in p.death_tokens:
                if tid.startswith("sdk_"):
                    continue          # Дохляки — карты барахолки, не жетоны
                tok = self.zhdk.get(tid)
                _pen = (tok.get("vp_penalty", -3) if tok else -3)
                vp += _pen
                add_step(f"Жетон «{tok.get('name', tid) if tok else tid}»", _pen, "bad")
            weak_count = sum(1 for cid in pool if self.cards[cid].type == WEAK_STICK_TYPE)
            if "dk_16" in p.death_tokens and "leg_viagrus" not in pool:
                vp -= weak_count
                add_step(f"Жетон «{self.zhdk.get('dk_16',{}).get('name','Вялая смерть')}»: палочки вдвойне", -weak_count, "bad")
            if "dk_4" in p.death_tokens and p.is_loshara:
                vp -= 5
                add_step(f"Жетон «{self.zhdk.get('dk_4',{}).get('name','Лошара!')}»: штраф удвоен", -5, "bad")
            # Два сапога взаимно уничтожаются в конце игры вместе со штрафами.
            if "dk_13" in p.death_tokens and "dk_14" in p.death_tokens:
                _pair = -(self.zhdk["dk_13"].get("vp_penalty", -8) + self.zhdk["dk_14"].get("vp_penalty", -8))
                vp += _pair
                add_step("Два сапога — пара: штрафы сняты", _pair, "good")
            real_tokens = [t for t in p.death_tokens if not t.startswith("sdk_")]
            scores[p.id] = {"vp": vp, "legends": legends,
                            "death_tokens": len(real_tokens), "steps": steps}
        self.logs.append("=== ИГРА ОКОНЧЕНА ===")
        best = max(scores.items(), key=lambda kv: (kv[1]["vp"], kv[1]["legends"], -kv[1]["death_tokens"]))
        self.winner = best[0]
        winner_name = self.get_player(self.winner).name
        self.log(f"Победитель: {winner_name} ({scores[self.winner]['vp']} ПО)")
        self.final_scores = scores

    # ------------------------------------------------------------------ #
    # Сериализация состояния для фронтенда
    # ------------------------------------------------------------------ #
    def card_public(self, cid: str) -> dict:
        """Полные данные карты для показа в окнах решений.

        Раньше сюда клали только id и name — из-за этого в карточке
        вылезали «undefined» вместо стоимости и мощи.
        """
        c = self.cards[cid]
        return {"id": c.id, "name": c.name, "type": c.type, "cost": c.cost,
                "power": c.power, "vp": c.vp, "text": c.full_text}

    def to_public_dict(self, viewer_id: Optional[str] = None) -> dict:
        def card_brief(cid):
            c = self.cards[cid]
            return {"id": c.id, "name": c.name, "type": c.type, "cost": c.cost,
                    "power": c.power, "vp": c.vp, "has_attack": c.has_attack,
                    "activation": c.activation or c.id in {"beast_jaba", "spell_magicspill", "wiz_marmemage", "leg_throne"},
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
                # Полный список жетонов: у части из них постоянные эффекты
                # (например «Палочный беспредел»), игрок должен их видеть.
                "death_token_cards": [
                    {
                        "id": tid,
                        "name": self.zhdk.get(tid, {}).get("name", tid),
                        "text": self.zhdk.get(tid, {}).get("effect_text", ""),
                        "vp": self.zhdk.get(tid, {}).get("vp_penalty", -3),
                        "permanent": bool(self.zhdk.get(tid, {}).get("postoyanka")),
                    }
                    for tid in p.death_tokens
                ],
                "property_id": p.property_id,
                "property": ({"id": p.property_id, "name": self.svo[p.property_id]["name"], "text": self.svo[p.property_id]["effect_text"]} if p.property_id in self.svo else None),
                "familiar":  card_brief(p.familiar_card_id) if p.familiar_card_id else None,
                "familiars": [card_brief(cid) for cid in p.familiar_card_ids],
                "familiar_bought": p.familiar_bought,
                "bought_familiars": list(p.bought_familiars),
            }
            if viewer_id == p.id:
                out["hand"] = [card_brief(c) for c in p.hand]
                out["discard_top"] = card_brief(p.discard[-1]) if p.discard else None
            players_out.append(out)

        pending_out = None
        if self.pending_decision:
            if viewer_id == self.pending_decision["player_id"]:
                pending_out = {key: value for key, value in self.pending_decision.items() if key != "player_id"}
            else:
                pending_out = {"waiting_for": self.pending_decision["player_name"]}

        visual_event = None
        if self.last_visual_event:
            visual_event = dict(self.last_visual_event)
            visual_event["cards"] = [card_brief(cid) for cid in visual_event.get("card_ids", []) if cid in self.cards]

        return {
            "players": players_out,
            "visual_event": visual_event,
            "pending_event": self.pending_event,
            "pending_decision": pending_out,
            "turn_player_id": self.active_player.id,
            "market": [card_brief(c) for c in self.market],
            "legend_market": [card_brief(c) for c in self.legend_market],
            "wild_magic_remaining": self.wild_magic_remaining,
            "vyal_remaining": self.vyal_remaining,
            "chips_bank": max(0, 40 - sum(p.chipsines for p in self.players)), 
            "main_deck_count": len(self.main_deck),
            "legend_deck_count": len(self.legend_deck),
            "undead_stack_count": len(self.undead_token_stack),
            "game_over": self.game_over,
            "winner": self.winner,
            "final_scores": [
                {
                    "id": pl.id,
                    "name": pl.name,
                    "avatar": pl.avatar,
                    "vp": self.final_scores[pl.id]["vp"],
                    "legends": self.final_scores[pl.id]["legends"],
                    "death_tokens": self.final_scores[pl.id]["death_tokens"],
                    "steps": self.final_scores[pl.id].get("steps", []),
                    "is_loshara": pl.is_loshara,
                    "controls_prize": pl.controls_prize,
                }
                for pl in sorted(
                    self.players,
                    key=lambda x: (-self.final_scores[x.id]["vp"],
                                   -self.final_scores[x.id]["legends"],
                                   self.final_scores[x.id]["death_tokens"]),
                )
            ] if self.final_scores else None,
            # Лента сгоревших карт: клиент проигрывает анимацию по seq.
            "destroy_reel": self.destroy_reel[-4:],
            # 30 строк вытеснялись цепочкой Беспределов — держим больше.
            "logs": self.logs[-100:],
        }
