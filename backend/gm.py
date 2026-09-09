"""Скрытая панель ведущего (GM / debug-режим).

Зачем: если в партии всплывает баг (не та цена, застрявшая карта, кривой
подсчёт жизней), хозяин может починить стол на лету, не переигрывая партию.

Как защищено — два независимых замка:

1. Клиентский: панель открывается секретным сочетанием клавиш, её нет
   в интерфейсе и она не приходит в состояние обычным игрокам.
2. Серверный (главный): КАЖДАЯ команда обязана прийти с правильным токеном.
   Клиентскую защиту любой игрок обходит через DevTools за минуту, поэтому
   именно токен решает, кто ведущий. Токен лежит в файле gm_token.txt рядом
   с проектом (в .gitignore) и в игру никогда не отправляется —
   сравнивается только присланная строка.

Боты сюда попасть не могут в принципе: команды приходят только из
WebSocket-соединения живого игрока, а у ботов соединения нет.
"""
from __future__ import annotations

import hmac
import os
import secrets
from typing import Optional

_ROOT = os.path.join(os.path.dirname(__file__), "..")
TOKEN_FILE = os.path.join(_ROOT, "gm_token.txt")

# Сколько сущностей за раз можно накинуть — защита от опечатки в духе «99999».
MAX_DELTA = 999


def _read_token_file() -> str:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def ensure_token() -> str:
    """Вернуть токен ведущего, создав файл при первом запуске."""
    token = os.environ.get("KRUTAGIDON_GM_TOKEN", "").strip() or _read_token_file()
    if not token:
        token = secrets.token_hex(4)          # 8 символов — удобно набрать руками
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(token + "\n")
        except OSError:
            pass
    return token


GM_TOKEN = ensure_token()


def check_token(value: Optional[str]) -> bool:
    """Сравнение в постоянном времени, чтобы токен нельзя было подобрать."""
    if not value or not GM_TOKEN:
        return False
    return hmac.compare_digest(str(value).strip(), GM_TOKEN)


def _clamp(value, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #

def apply(game, command: str, params: dict, gm_name: str = "Ведущий") -> dict:
    """Выполнить команду ведущего над текущей партией.

    Возвращает {"ok": True, "message": ...} либо {"error": ...}.
    Каждое действие пишется в общий лог партии: тайных правок не бывает,
    игроки должны видеть, что стол чинили.
    """
    if not game:
        return {"error": "Партия ещё не началась"}

    def target(pid=None):
        return game.get_player(pid or params.get("player_id"))

    # --- ресурсы ---------------------------------------------------------
    if command == "add_power":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        delta = _clamp(params.get("amount", 1), -MAX_DELTA, MAX_DELTA)
        p.power_available = max(0, p.power_available + delta)
        return _done(game, f"{gm_name}: {p.name} получает {delta:+d} мощи "
                           f"(стало {p.power_available})")

    if command == "add_chips":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        delta = _clamp(params.get("amount", 1), -MAX_DELTA, MAX_DELTA)
        p.chipsines = max(0, p.chipsines + delta)
        return _done(game, f"{gm_name}: {p.name} получает {delta:+d} чипсин "
                           f"(стало {p.chipsines})")

    if command == "set_life":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        p.life = _clamp(params.get("value", p.life), 0, p.max_life)
        return _done(game, f"{gm_name}: у {p.name} теперь {p.life} жизней")

    if command == "add_life":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        delta = _clamp(params.get("amount", 1), -MAX_DELTA, MAX_DELTA)
        p.life = max(0, min(p.max_life, p.life + delta))
        return _done(game, f"{gm_name}: {p.name} {delta:+d} жизней (стало {p.life})")

    # --- статусы ---------------------------------------------------------
    if command == "kill":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        killer = target(params.get("killer_id")) if params.get("killer_id") else None
        p.life = 0
        game.log(f"{gm_name}: убивает {p.name}"
                 + (f" (убийца — {killer.name})" if killer else ""))
        game._handle_death(p, killer)
        return _done(game, f"{p.name} подох по воле ведущего")

    if command == "revive":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        p.life = game._revive_life(p)
        return _done(game, f"{gm_name}: воскрешает {p.name} ({p.life} жизней)")

    if command == "set_loshara":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        game.set_loshara(p, bool(params.get("value", True)))
        return _done(game, f"{gm_name}: правит статус лошары у {p.name}")

    if command == "give_prize":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        for other in game.players:
            other.controls_prize = False
        p.controls_prize = True
        game.prize_holder = p.id
        return _done(game, f"{gm_name}: главный приз Крутагидона передан {p.name}")

    # --- жетоны ЖДК ------------------------------------------------------
    if command == "add_token":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        tid = params.get("token_id")
        if tid not in game.zhdk:
            return {"error": "Такого жетона нет"}
        p.death_tokens.append(tid)
        return _done(game, f"{gm_name}: {p.name} получает жетон "
                           f"«{game.zhdk[tid].get('name', tid)}»")

    if command == "remove_token":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        tid = params.get("token_id")
        if tid not in p.death_tokens:
            return {"error": "У игрока нет такого жетона"}
        p.death_tokens.remove(tid)
        return _done(game, f"{gm_name}: у {p.name} снят жетон "
                           f"«{game.zhdk.get(tid, {}).get('name', tid)}»")

    # --- карты -----------------------------------------------------------
    if command == "give_card":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        cid = params.get("card_id")
        if cid not in game.cards:
            return {"error": "Такой карты нет в базе"}
        where = params.get("destination", "hand")
        if where not in {"hand", "discard", "deck_top", "in_play"}:
            where = "hand"
        if where == "in_play":
            p.zone_in_play.append(cid)
        else:
            p.hand.append(cid) if where == "hand" else (
                p.deck.append(cid) if where == "deck_top" else p.discard.append(cid))
        return _done(game, f"{gm_name}: {p.name} получает «{game.cards[cid].name}» "
                           f"({where})")

    if command == "remove_card":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        cid = params.get("card_id")
        for zone in ("hand", "discard", "deck", "zone_in_play", "in_play_this_turn"):
            cards = getattr(p, zone)
            if cid in cards:
                cards.remove(cid)
                return _done(game, f"{gm_name}: у {p.name} убрана карта "
                                   f"«{game.cards[cid].name}» ({zone})")
        return {"error": "Карта у игрока не найдена"}

    if command == "draw":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        n = _clamp(params.get("amount", 1), 1, 20)
        game.draw_cards(p, n)
        return _done(game, f"{gm_name}: {p.name} берёт {n} карт(ы)")

    # --- стол ------------------------------------------------------------
    if command == "refill_market":
        game.market.clear()
        game.legend_market.clear()
        game._fill_market_no_resolve()
        game._fill_legend_market_no_resolve()
        return _done(game, f"{gm_name}: барахолка и зал легенд пересобраны")

    if command == "set_turn":
        p = target()
        if not p:
            return {"error": "Игрок не найден"}
        game.turn_idx = game.players.index(p)
        return _done(game, f"{gm_name}: ход передан игроку {p.name}")

    if command == "clear_pending":
        # Спасательная кнопка: партия зависла на окне выбора/атаке.
        game.pending_decision = None
        game.pending_event = None
        game.pending_attack = None
        game.event_queue.clear()
        # Очередь отложенных решений тоже чистим, иначе после «разморозки»
        # тут же всплывёт следующий зависший вопрос.
        if hasattr(game, "_decision_stack"):
            game._decision_stack.clear()
        game._decision_callback = None
        if hasattr(game, "event_viewers"):
            game.event_viewers.clear()
        return _done(game, f"{gm_name}: зависшие окна выбора сброшены")

    if command == "finish_game":
        game._finish_game()
        return _done(game, f"{gm_name}: партия завершена досрочно, считаем очки")

    return {"error": f"Неизвестная команда ведущего: {command}"}


def _done(game, message: str) -> dict:
    game.log(message)
    return {"ok": True, "message": message}
