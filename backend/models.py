"""
Модель карты. Грузится напрямую из cards.json (сгенерирован из Excel-базы).
Никаких хардкоженных характеристик карт в коде быть не должно —
единственный источник правды это cards.json.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json
import os

CARDS_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "cards.json")

# Типы карт, которые замешиваются в ОСНОВНУЮ колоду (рынок из 5 карт)
MAIN_DECK_TYPES = {"Волшебник", "Заклинание", "Место", "Сокровище", "Тварь", "Беспредел", "Дохляк"}
# Типы карт, которые замешиваются в колоду ЛЕГЕНД (рынок из 3 карт)
LEGEND_DECK_TYPES = {"Легенда", "Мегабеспредел"}
# Стартовые карты — раздаются в личную колоду при подготовке, НЕ часть рынка
STARTER_TYPES = {"Затравка"}
# Особые стопки покупки
WILD_MAGIC_TYPE = "Шальная магия"
WEAK_STICK_TYPE = "Вялая палочка"
FAMILIAR_TYPE = "Фамильяр"


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower().startswith("да")


def _to_int(v, default=0) -> int:
    try:
        if v is None or v == "" or v == "-":
            return default
        return int(v)
    except (ValueError, TypeError):
        return default


@dataclass
class Card:
    id: str
    name: str
    type: str
    legend_subtype: Optional[str] = None
    cost: int = 0
    power: int = 0          # мощь, которую карта даёт при розыгрыше
    vp: int = 0             # победные очки в конце игры
    has_attack: bool = False
    attack_text: str = ""
    has_defense: bool = False
    defense_text: str = ""
    postoyanka: bool = False
    activation: bool = False
    act_before: str = ""
    act_after: str = ""
    full_text: str = ""
    chipsina_symbol: int = 0
    familiar_owner: Optional[str] = None
    notes: str = ""
    photo: Optional[str] = None
    qty_in_deck: int = 1

    @property
    def is_attack(self) -> bool:
        return self.has_attack

    @property
    def types_for_matching(self) -> set:
        """Для легенд карта считается сразу двух типов (стр. 11 правил)."""
        s = {self.type}
        if self.type == "Легенда" and self.legend_subtype:
            s.add(self.legend_subtype)
        return s


def load_all_cards() -> dict[str, Card]:
    with open(CARDS_JSON_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    cards = {}
    for r in raw:
        c = Card(
            id=r["id"],
            name=r["name"] or r["id"],
            type=r["type"] or "",
            legend_subtype=r.get("legend_subtype") or None,
            cost=_to_int(r.get("cost")),
            power=_to_int(r.get("power")),
            vp=_to_int(r.get("vp")),
            has_attack=_to_bool(r.get("has_attack")),
            attack_text=r.get("attack_text") or "",
            has_defense=_to_bool(r.get("has_defense")),
            defense_text=r.get("defense_text") or "",
            postoyanka=_to_bool(r.get("postoyanka")),
            activation=_to_bool(r.get("activation")),
            act_before=r.get("act_before") or "",
            act_after=r.get("act_after") or "",
            full_text=r.get("full_text") or "",
            chipsina_symbol=_to_int(r.get("chipsina_symbol")),
            familiar_owner=r.get("familiar_owner") or None,
            notes=r.get("notes") or "",
            photo=r.get("photo"),
            qty_in_deck=_to_int(r.get("qty_in_deck"), default=1),
        )
        cards[c.id] = c
    return cards
