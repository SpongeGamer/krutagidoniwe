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
from typing import Optional

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
    life: int = START_LIFE
    max_life: int = MAX_LIFE
    chipsines: int = 0
    death_tokens: list = field(default_factory=list)   # ids жетонов ЖДК
    is_loshara: bool = False
    familiar_card_id: Optional[str] = None
    familiar_bought: bool = False
    property_id: Optional[str] = None
    controls_prize: bool = False

    deck: list = field(default_factory=list)      # stack, top = end of list
    hand: list = field(default_factory=list)
    discard: list = field(default_factory=list)
    zone_in_play: list = field(default_factory=list)   # постоянки, лежащие "в игре"

    power_available: int = 0
    in_play_this_turn: list = field(default_factory=list)  # сыгранные в этот ход
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

    def hand_limit(self, player: Player) -> int:
        return HAND_SIZE + player.hand_limit_bonus

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

    # ------------------------------------------------------------------ #
    # Ход
    # ------------------------------------------------------------------ #
    def start_turn(self):
        self._fill_market_resolving()
        self._fill_legend_market_resolving()
        p = self.active_player
        p.power_available = 0
        p.in_play_this_turn = []
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
        if self.pending_attack:
            return {"error": "Дождитесь разрешения текущей атаки"}

        card = self.cards[card_id]
        player.hand.remove(card_id)
        player.in_play_this_turn.append(card_id)
        player.power_available += card.power

        from . import effects
        handler = effects.get_effect(card_id)
        if handler:
            handler(self, player, card, **kwargs)
        elif card.full_text and card.full_text not in ("(Эффекта нет.)",):
            self.log(f"[TODO] {card.name}: текст «{card.full_text}» пока не реализован, применена только мощь")

        if card.postoyanka and not self.pending_attack:
            player.zone_in_play.append(card_id)
        elif not self.pending_attack:
            player.discard.append(card_id)
        # если атака в процессе (pending_attack), карта "дозакинется" в сброс/постоянку
        # после resolve_pending_attack()

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
        if self.pending_attack:
            return {"error": "Дождитесь разрешения текущей атаки"}
        if card_id not in self.market and card_id not in self.legend_market:
            return {"error": "Этой карты нет на барахолке"}
        card = self.cards[card_id]
        if card.cost > player.power_available:
            return {"error": "Не хватает мощи"}
        player.power_available -= card.cost
        if card_id in self.market:
            self.market.remove(card_id)
            self._fill_market_resolving()
        else:
            self.legend_market.remove(card_id)
            self._fill_legend_market_resolving()
        player.discard.append(card_id)
        self.log(f"{player.name}: покупает {card.name} (-{card.cost} мощи)")
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
        player.discard.append(wild_card.id)
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
        player.discard.append(card.id)
        self.log(f"{player.name}: покупает своего фамильяра {card.name}")
        return {"ok": True}

    def end_turn(self, player: Player) -> dict:
        if player.id != self.active_player.id:
            return {"error": "Сейчас не ваш ход"}
        if self.pending_attack:
            return {"error": "Дождитесь разрешения текущей атаки"}
        player.discard.extend(player.hand)
        player.hand = []
        player.discard.extend(player.in_play_this_turn)
        # постоянки уже перенесены в zone_in_play при розыгрыше, не дублируем
        player.in_play_this_turn = []
        player.power_available = 0
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
        target.life -= amount
        self.last_damage_target_id = target_id
        self.log(f"{target.name} отхватывает {amount} урона от «{card_name}» ({source.name})")
        if target.life <= 0:
            self._handle_death(target, killer=source)
            return True
        return False

    def declare_attack(self, source: Player, card: Card, targets, amount: int):
        """
        Массовая атака (targets: 'all_enemies' | 'left_right' | list[player_id]).
        Упрощённая версия без интерактивных карт защиты — сразу применяет урон
        (это заглушка; интерактивная защита будет добавлена отдельно вместе
        с реальными картами защиты из основной колоды).
        """
        target_players = self._resolve_target_group(source, targets)
        for t in target_players:
            self.deal_damage(source, t.id, amount, card.name)

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
                    "power": c.power, "vp": c.vp, "text": c.full_text, "photo": c.photo}

        players_out = []
        for p in self.players:
            out = {
                "id": p.id, "name": p.name, "life": p.life, "max_life": p.max_life,
                "chipsines": p.chipsines, "is_loshara": p.is_loshara,
                "controls_prize": p.controls_prize,
                "power_available": p.power_available,
                "hand_count": len(p.hand),
                "deck_count": len(p.deck), "discard_count": len(p.discard),
                "zone_in_play": [card_brief(c) for c in p.zone_in_play],
                "death_tokens": len(p.death_tokens),
                "familiar": card_brief(p.familiar_card_id) if p.familiar_card_id else None,
                "familiar_bought": p.familiar_bought,
            }
            if viewer_id == p.id:
                out["hand"] = [card_brief(c) for c in p.hand]
            players_out.append(out)

        return {
            "players": players_out,
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
