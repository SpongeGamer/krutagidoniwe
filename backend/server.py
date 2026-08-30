"""FastAPI + WebSocket сервер для комнат Крутагидона."""
from __future__ import annotations
import asyncio
import json
import os
import random
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .game import GameState, START_LIFE
from .models import load_all_cards

app = FastAPI()
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..")


def load_properties() -> list[dict]:
    with open(os.path.join(_DATA_DIR, "svo.json"), encoding="utf-8") as f:
        return json.load(f)


PROPERTIES = load_properties()
ALL_CARDS = load_all_cards()


def load_boards() -> list[dict]:
    with open(os.path.join(_DATA_DIR, "boards.json"), encoding="utf-8") as f:
        boards = json.load(f)
    result = []
    for board in boards:
        familiar = ALL_CARDS[board["familiar_id"]]
        result.append({
            "id": board["familiar_id"],
            "wizard_name": board["colduna_name"],
            "familiar_id": familiar.id,
            "familiar_name": familiar.name,
            "familiar_text": familiar.full_text,
            # Полные данные карты — фронтенд показывает картинку и читаемое
            # описание в окне просмотра, без обрезки текста.
            "cost": familiar.cost,
            "power": familiar.power,
            "vp": familiar.vp,
            "type": familiar.type,
            "attack_text": familiar.attack_text,
            "defense_text": familiar.defense_text,
        })
    return result


BOARDS = load_boards()


class Room:
    def __init__(self, room_id: str):
        self.id = room_id
        self.game: Optional[GameState] = None
        self.connections: dict[str, WebSocket] = {}
        self.player_names: dict[str, str] = {}
        self.player_avatars: dict[str, str] = {}
        self.bot_ids: set[str] = set()
        # Каждому игроку сервер предлагает две случайные черты до старта.
        self.property_offers: dict[str, list[dict]] = {}
        self.selected_properties: dict[str, str] = {}
        # Фамильяры выдаются только после выбора свойства.
        self.familiar_offers: dict[str, list[dict]] = {}
        self.selected_familiars: dict[str, list[str]] = {}
        self.started = False
        self.host_id: Optional[str] = None
        self.settings = {"zhdk_mode": "standard", "zhdk_count": None}
        # Пауза: партия замирает, пока кто-то отвалился или все решили отдохнуть.
        self.offline: set[str] = set()
        self.manual_pause = False

    @property
    def paused(self) -> bool:
        return bool(self.manual_pause or self.offline)

    def pause_info(self) -> dict:
        names = [self.player_names.get(pid, "Колдун") for pid in sorted(self.offline)]
        if names:
            reason = ("Ждём: " + ", ".join(names)) if len(names) > 1 else f"Ждём: {names[0]}"
            kind = "offline"
        elif self.manual_pause:
            reason = "Перерыв — все отдыхают"
            kind = "manual"
        else:
            return {"paused": False}
        return {"paused": True, "reason": reason, "kind": kind, "waiting_for": names}

    def ensure_property_offer(self, player_id: str):
        """Две карты свойств резервируются за игроком и не повторяются у других."""
        if player_id not in self.property_offers:
            reserved = {p["id"] for offers in self.property_offers.values() for p in offers}
            available = [p for p in PROPERTIES if p["id"] not in reserved]
            self.property_offers[player_id] = random.sample(available, k=min(2, len(available)))

    def ensure_familiar_offer(self, player_id: str):
        """После свойства выдаём две уникальные карты фамильяров."""
        if player_id in self.familiar_offers:
            return
        reserved = {board["id"] for offers in self.familiar_offers.values() for board in offers}
        selected = {fid for fids in self.selected_familiars.values() for fid in fids}
        available = [board for board in BOARDS if board["id"] not in reserved and board["id"] not in selected]
        self.familiar_offers[player_id] = random.sample(available, k=min(2, len(available)))

    def familiar_choices_for(self, player_id: str) -> list[dict]:
        if player_id not in self.selected_properties:
            return []
        current = self.selected_familiars.get(player_id, [])
        if self.selected_properties.get(player_id) == "svo_2" and len(current) >= 2:
            # Третий фамильяр — любой, кого НЕ ВЫБРАЛИ другие игроки.
            # Чужие «предложенные, но не выбранные» карты тут не блокируют:
            # иначе при полном столе выбирать было бы не из чего.
            taken = {fid for pid, fids in self.selected_familiars.items()
                     if pid != player_id for fid in fids}
            free = [b for b in BOARDS if b["id"] not in taken and b["id"] not in current]
            return free
        return self.familiar_offers.get(player_id, [])

    def add_bot(self) -> Optional[str]:
        if self.started or len(self.player_names) >= 5:
            return None
        index = len(self.bot_ids) + 1
        bot_id = f"bot-{uuid.uuid4().hex[:6]}"
        self.bot_ids.add(bot_id)
        self.player_names[bot_id] = f"Бот {index}"
        self.player_avatars[bot_id] = "🤖"
        self.ensure_property_offer(bot_id)
        # Бот выбирает первое уникальное свойство, затем первого фамильяра.
        if self.property_offers[bot_id]:
            prop_id = self.property_offers[bot_id][0]["id"]
            self.selected_properties[bot_id] = prop_id
            self.ensure_familiar_offer(bot_id)
            offers = self.familiar_offers.get(bot_id, [])
            needed = 3 if prop_id == "svo_2" else 1
            selected = [b["id"] for b in offers[:needed]]
            # Для svo_2 добавляем первого доступного ничейного третьим.
            if needed == 3 and len(selected) < 3:
                used = {fid for fids in self.selected_familiars.values() for fid in fids} | set(selected)
                extra = next((b["id"] for b in BOARDS if b["id"] not in used), None)
                if extra:
                    selected.append(extra)
            self.selected_familiars[bot_id] = selected
        return bot_id

    def remove_player(self, player_id: str):
        """Убрать игрока или бота из лобби со всеми его выборами."""
        self.player_names.pop(player_id, None)
        self.player_avatars.pop(player_id, None)
        self.selected_properties.pop(player_id, None)
        self.selected_familiars.pop(player_id, None)
        self.property_offers.pop(player_id, None)
        self.familiar_offers.pop(player_id, None)
        self.bot_ids.discard(player_id)
        self.offline.discard(player_id)
        self.connections.pop(player_id, None)

    def log_line(self, text: str):
        if self.game:
            self.game.log(text)

    def reset_to_lobby(self):
        """Партия окончена — всех обратно в лобби, состав стола сохраняем.

        Свойства и фамильяры раздаются заново: иначе следующая партия
        стартовала бы с теми же картами, что и предыдущая.
        """
        self.game = None
        self.started = False
        self.manual_pause = False
        self.offline.clear()
        self.property_offers.clear()
        self.selected_properties.clear()
        self.familiar_offers.clear()
        self.selected_familiars.clear()
        for pid in list(self.player_names):
            self.ensure_property_offer(pid)
        # Боты снова выбирают свойство и фамильяра, иначе застрянут «не готовы».
        for bot_id in list(self.bot_ids):
            offers = self.property_offers.get(bot_id, [])
            if not offers:
                continue
            prop_id = offers[0]["id"]
            self.selected_properties[bot_id] = prop_id
            self.ensure_familiar_offer(bot_id)
            fam_offers = self.familiar_offers.get(bot_id, [])
            needed = 3 if prop_id == "svo_2" else 1
            selected = [b["id"] for b in fam_offers[:needed]]
            if needed == 3 and len(selected) < 3:
                used = {fid for fids in self.selected_familiars.values() for fid in fids} | set(selected)
                extra = [b["id"] for b in BOARDS if b["id"] not in used][:3 - len(selected)]
                selected.extend(extra)
            self.selected_familiars[bot_id] = selected

    def is_bot(self, player_id: Optional[str]) -> bool:
        return bool(player_id and player_id in self.bot_ids)

    def _resolve_bot_decisions(self) -> bool:
        """Вернуть True, если бот сделал действие. Окна человека не трогаем."""
        game = self.game
        if not game:
            return False
        if game.pending_event:
            game.resolve_event()
            return True
        if game.pending_decision:
            pid = game.pending_decision["player_id"]
            if not self.is_bot(pid):
                return False
            bot = game.get_player(pid)
            options = game.pending_decision.get("options", [])
            if bot and options:
                # Бот обычно берёт первый допустимый вариант; это намеренно простой тестовый ИИ.
                game.resolve_decision(bot, options[0]["id"])
                return True
        return False

    def pick_bot_target(self, bot, enemies):
        """Кого бот бьёт.

        Раньше всегда брался enemies[0] — то есть один и тот же игрок
        получал все атаки подряд. Теперь бот целится осмысленно:
        добивает раненых, уважает лидера по очкам и иногда бьёт наугад.
        """
        if not enemies:
            return None
        if len(enemies) == 1:
            return enemies[0]

        # 20% ходов — случайная цель, чтобы бот не был предсказуемым.
        if random.random() < 0.2:
            return random.choice(enemies)

        def threat(e):
            score = 0
            score += len(e.zone_in_play) * 2          # много постоянок — опасен
            score += e.chipsines
            score += 3 if e.controls_prize else 0     # держит приз — цель номер один
            score -= e.life // 5                      # раненых добиваем охотнее
            return score

        # Кого можно убить прямо сейчас — того и бьём.
        weakest = min(enemies, key=lambda e: e.life)
        if weakest.life <= 6:
            return weakest
        # При равной угрозе выбираем случайного из лучших, иначе max()
        # всегда возвращал первого в списке — то есть одного и того же игрока.
        best = max(threat(e) for e in enemies)
        return random.choice([e for e in enemies if threat(e) == best])

    async def run_bots(self):
        """Пошаговый тестовый ИИ: после каждого действия рассылает состояние.
        Поэтому человек видит карты, покупки и смену хода, а не только итог.
        """
        if not self.game:
            return
        safety = 0
        announced_bot_id: Optional[str] = None
        while safety < 200 and not self.game.game_over:
            if self.paused:      # на паузе боты тоже замирают
                break
            safety += 1
            game = self.game
            if game.pending_event:
                # Беспредел человека всегда ждёт клика; бот может продолжить свой.
                if not self.is_bot(game.active_player.id):
                    break
                # Сначала ПОКАЗЫВАЕМ карту всем и держим паузу, чтобы люди
                # успели прочитать, и только потом применяем эффект.
                await self.broadcast()
                await asyncio.sleep(6.0)
                game.resolve_event()
                await self.broadcast()
                await asyncio.sleep(1.1)
                continue
            if game.pending_decision:
                pid = game.pending_decision["player_id"]
                if not self.is_bot(pid):
                    break
                bot = game.get_player(pid)
                options = game.pending_decision.get("options", [])
                if not bot or not options:
                    break
                # Люди должны успеть прочитать, что происходит у бота:
                # сначала показываем вопрос, держим паузу, только потом отвечаем.
                await self.broadcast()
                await asyncio.sleep(3.2)
                game.resolve_decision(bot, options[0]["id"])
                await self.broadcast()
                await asyncio.sleep(1.4)
                continue
            active = game.active_player
            if not self.is_bot(active.id):
                break
            if announced_bot_id != active.id:
                announced_bot_id = active.id
                game.emit_visual_event("turn", active)
                await self.broadcast()
                await asyncio.sleep(1.0)
                continue
            # Одно действие бота за итерацию: его можно увидеть на столе.
            if active.hand:
                # Сначала карты без атаки — копим мощь, потом бьём.
                cid = min(active.hand, key=lambda c: (game.cards[c].has_attack, -game.cards[c].power))
                card = game.cards[cid]
                params = {}
                enemies = [e for e in game.enemies_of(active) if e.is_alive()]
                text_low = (card.full_text or "").lower()
                wants_target = any(w in text_low for w in
                                   ("выбранн", "выбери", "левого", "правого", "левому", "правому"))
                if (card.has_attack or wants_target) and enemies:
                    params["target_id"] = self.pick_bot_target(active, enemies).id
                    params["target_ids"] = [e.id for e in enemies]
                game.play_card(active, cid, **params)
                await self.broadcast()
                await asyncio.sleep(1.1)
                continue
            affordable = [cid for cid in game.market + game.legend_market if game.cards[cid].cost <= active.power_available]
            if affordable:
                # Берём самое дорогое из доступного — оно обычно и сильнее.
                chosen = max(affordable, key=lambda cid: (game.cards[cid].vp, game.cards[cid].cost))
                game.buy_card(active, chosen)
                game.emit_visual_event("buy", active, [chosen], "market", "discard")
                await self.broadcast()
                await asyncio.sleep(1.1)
                continue
            game.end_turn(active)
            await self.broadcast()
            await asyncio.sleep(1.1)

    async def broadcast(self):
        if not self.game:
            return
        pause = self.pause_info()
        for pid, ws in list(self.connections.items()):
            try:
                state = self.game.to_public_dict(viewer_id=pid)
                state["pause"] = pause
                state["offline_ids"] = sorted(self.offline)
                state["is_host"] = (pid == self.host_id)
                await ws.send_json({"type": "state", "state": state})
            except Exception:
                pass

    async def broadcast_lobby(self):
        players = [
            {"id": pid, "name": name, "avatar": self.player_avatars.get(pid, "🧙"),
             "is_bot": self.is_bot(pid),
             "ready": len(self.selected_familiars.get(pid, [])) >= (3 if self.selected_properties.get(pid) == "svo_2" else 1)}
            for pid, name in self.player_names.items()
        ]
        for pid, ws in list(self.connections.items()):
            try:
                await ws.send_json({
                    "type": "lobby",
                    "players": players,
                    "started": self.started,
                    "property_choices": self.property_offers.get(pid, []),
                    "selected_property_id": self.selected_properties.get(pid),
                    "familiar_choices": self.familiar_choices_for(pid),
                    "selected_familiar_ids": self.selected_familiars.get(pid, []),
                    "familiar_required": 3 if self.selected_properties.get(pid) == "svo_2" else 1,
                    "host_id": self.host_id,
                    "is_host": pid == self.host_id,
                    "settings": self.settings,
                })
            except Exception:
                pass


ROOMS: dict[str, Room] = {}


def get_or_create_room(room_id: str) -> Room:
    if room_id not in ROOMS:
        ROOMS[room_id] = Room(room_id)
    return ROOMS[room_id]


@app.websocket("/ws/{room_id}")
async def ws_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    room = get_or_create_room(room_id)
    player_id: Optional[str] = None

    try:
        join_msg = await websocket.receive_json()
        name = (join_msg.get("name") or "Колдун").strip()[:40]
        avatar = (join_msg.get("avatar") or "🧙")[:4]
        saved_id = join_msg.get("player_id")

        # Возвращение в идущую партию: узнаём игрока по сохранённому id.
        returning = bool(saved_id and saved_id in room.player_names)
        if returning:
            player_id = saved_id
            room.offline.discard(player_id)
            # Имя/аватар не перетираем: игрок уже сидит за столом под ними.
            room.log_line(f"{room.player_names[player_id]} вернулся в игру")
        else:
            if room.started:
                # Партия уже идёт — новых за стол не сажаем, только зрителем.
                await websocket.send_json({
                    "type": "error",
                    "message": "Партия уже началась. Попроси хозяина комнаты начать новую.",
                })
                await websocket.close()
                return
            player_id = saved_id or str(uuid.uuid4())[:8]
            room.player_names[player_id] = name
            room.player_avatars[player_id] = avatar
            room.ensure_property_offer(player_id)

        room.connections[player_id] = websocket
        if room.host_id is None or room.host_id not in room.player_names:
            room.host_id = player_id
        await websocket.send_json({
            "type": "joined",
            "player_id": player_id,
            "room_id": room.id,
            "returning": returning,
        })

        if room.started and room.game:
            await room.broadcast()
            if not room.paused:
                await room.run_bots()
                await room.broadcast()
        else:
            await room.broadcast_lobby()

        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")

            # Пинг от клиента: держит соединение живым через прокси.
            # CloudPub и подобные сервисы рвут WebSocket, если по нему
            # долго ничего не идёт, — отсюда и вылетали 502 в лобби.
            if action == "ping":
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    pass
                continue

            # --- Пауза: доступна всем, останавливает партию для отдыха ---
            if action == "toggle_pause":
                if room.offline:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Партия и так на паузе: ждём отключившихся",
                    })
                else:
                    room.manual_pause = not room.manual_pause
                    who = room.player_names.get(player_id, "Колдун")
                    room.log_line(f"{who} {'поставил партию на паузу' if room.manual_pause else 'снял паузу'}")
                    await room.broadcast()
                continue

            # Пока стоит пауза, игровые действия не проходят.
            if room.started and room.paused and action not in {"toggle_pause"}:
                await websocket.send_json({
                    "type": "error",
                    "message": room.pause_info().get("reason", "Партия на паузе"),
                })
                continue

            if action == "add_bot" and not room.started:
                if player_id != room.host_id:
                    await websocket.send_json({"type": "error", "message": "Бота может добавить только хост"})
                elif not room.add_bot():
                    await websocket.send_json({"type": "error", "message": "Нельзя добавить больше ботов"})
                await room.broadcast_lobby()
                continue

            # Хост убирает лишнего бота или игрока из лобби.
            if action == "kick_player" and not room.started:
                target_id = msg.get("player_id")
                if player_id != room.host_id:
                    await websocket.send_json({"type": "error",
                                               "message": "Убирать игроков может только хост"})
                elif target_id == room.host_id:
                    await websocket.send_json({"type": "error",
                                               "message": "Хост не может выгнать сам себя"})
                elif target_id not in room.player_names:
                    await websocket.send_json({"type": "error",
                                               "message": "Такого игрока в комнате нет"})
                else:
                    kicked_name = room.player_names.get(target_id, "Колдун")
                    was_human = not room.is_bot(target_id)
                    sock = room.connections.get(target_id)
                    room.remove_player(target_id)
                    # Человеку сообщаем и закрываем соединение, иначе он
                    # продолжит висеть в комнате с открытым лобби.
                    if was_human and sock:
                        try:
                            await sock.send_json({"type": "kicked",
                                                  "message": f"{kicked_name}, хост убрал тебя из комнаты"})
                            await sock.close()
                        except Exception:
                            pass
                await room.broadcast_lobby()
                continue

            if action == "configure_room" and not room.started:
                if player_id != room.host_id:
                    await websocket.send_json({"type": "error", "message": "Настройки комнаты меняет только хост"})
                    continue
                mode = msg.get("zhdk_mode", "standard")
                if mode not in {"standard", "all", "custom"}:
                    await websocket.send_json({"type": "error", "message": "Неизвестный режим ЖДК"})
                    continue
                count = None
                if mode == "custom":
                    try:
                        count = max(1, min(35, int(msg.get("zhdk_count", 12))))
                    except (ValueError, TypeError):
                        count = 12
                room.settings = {"zhdk_mode": mode, "zhdk_count": count}
                await room.broadcast_lobby()
                continue

            if action == "choose_familiar" and not room.started:
                if player_id not in room.selected_properties:
                    await websocket.send_json({"type": "error", "message": "Сначала выбери свойство"})
                    continue
                familiar_id = msg.get("familiar_id")
                current = room.selected_familiars.setdefault(player_id, [])
                property_id = room.selected_properties[player_id]
                required = 3 if property_id == "svo_2" else 1
                offered = {board["id"] for board in room.familiar_offers.get(player_id, [])}
                selected_by_other = {fid for pid, fids in room.selected_familiars.items() if pid != player_id for fid in fids}
                # Обычный игрок выбирает одну из двух предложенных. Свойство «Фамильяры»
                # оставляет обе предложенные карты и разрешает третью из ничейных.
                allowed = offered
                if property_id == "svo_2" and len(current) >= 2:
                    allowed = {board["id"] for board in BOARDS}
                if familiar_id not in allowed or familiar_id in selected_by_other:
                    await websocket.send_json({"type": "error", "message": "Этот фамильяр уже занят или недоступен"})
                elif familiar_id not in current and len(current) < required:
                    current.append(familiar_id)
                await room.broadcast_lobby()
                continue

            if action == "unchoose_familiar" and not room.started:
                # Игрок мог ткнуть не туда — даём снять выбор до старта партии.
                familiar_id = msg.get("familiar_id")
                current = room.selected_familiars.get(player_id, [])
                if familiar_id in current:
                    current.remove(familiar_id)
                await room.broadcast_lobby()
                continue

            if action == "choose_property" and not room.started:
                property_id = msg.get("property_id")
                allowed = {p["id"] for p in room.property_offers.get(player_id, [])}
                if property_id in allowed:
                    # Выпавшая пара фамильяров закрепляется за игроком навсегда:
                    # менять свойство можно, но перекатить фамильяров этим нельзя.
                    previous = room.selected_properties.get(player_id)
                    room.selected_properties[player_id] = property_id
                    room.ensure_familiar_offer(player_id)
                    # Выбор фамильяров ВСЕГДА за игроком — сервер за него не решает.
                    # При уходе со свойства «Фамильяры» лишние карты обрезаем,
                    # но уже сделанный выбор не трогаем.
                    if previous == "svo_2" and property_id != "svo_2":
                        current = room.selected_familiars.get(player_id, [])
                        if len(current) > 1:
                            room.selected_familiars[player_id] = current[:1]
                else:
                    await websocket.send_json({"type": "error", "message": "Выбери одно из предложенных свойств"})
                await room.broadcast_lobby()
                continue

            # Хост закрывает итоги — ВСЕХ возвращает в лобби, а не только себя.
            if action == "return_to_lobby":
                if player_id != room.host_id:
                    await websocket.send_json({"type": "error",
                                               "message": "Только хост может вернуть всех в лобби"})
                    continue
                if not room.started:
                    continue
                room.reset_to_lobby()
                for pid, sock in list(room.connections.items()):
                    try:
                        await sock.send_json({"type": "to_lobby"})
                    except Exception:
                        pass
                await room.broadcast_lobby()
                continue

            if action == "start_game":
                if not room.started:
                    missing_property = [pid for pid in room.player_names if pid not in room.selected_properties]
                    missing_familiar = [
                        pid for pid in room.player_names
                        if len(room.selected_familiars.get(pid, [])) < (3 if room.selected_properties.get(pid) == "svo_2" else 1)
                    ]
                    if missing_property or missing_familiar:
                        await websocket.send_json({"type": "error", "message": "Все игроки должны выбрать свойство и нужных фамильяров"})
                        continue
                    names_by_pid = room.player_names
                    room.game = GameState(list(names_by_pid.values()))
                    mode = room.settings["zhdk_mode"]
                    if mode == "all":
                        room.game.configure_undead_stack(len(room.game.zhdk))
                    elif mode == "custom":
                        room.game.configure_undead_stack(room.settings["zhdk_count"])
                    for (pid, _name), gp in zip(names_by_pid.items(), room.game.players):
                        gp.id = pid
                        gp.avatar = room.player_avatars.get(pid, "🧙")
                        gp.property_id = room.selected_properties.get(pid)
                        gp.familiar_card_ids = room.selected_familiars.get(pid, [])[:]
                        gp.familiar_card_id = gp.familiar_card_ids[0] if gp.familiar_card_ids else None
                        room.game.apply_property_setup(gp)
                    # Стартовые жизни: 20 из 25 возможных (правила, стр. 6).
                    # Исключения делает только apply_property_setup:
                    # «Главный приз» (svo_6) начинает с полными 25.
                    for gp in room.game.players:
                        if gp.is_loshara:
                            continue
                        if gp.property_id != "svo_6":
                            gp.life = min(gp.life, START_LIFE)
                    room.game.log(f"Настройка комнаты: ЖДК = {len(room.game.undead_token_stack)}")
                    room.game.start_turn()
                    room.started = True
                    room.game.log("Игра началась!")
                    for gp in room.game.players:
                        room.game.log(f"Старт {gp.name}: рука {len(gp.hand)}, колода {len(gp.deck)}, сброс {len(gp.discard)}")
                    await room.broadcast()
                    await room.run_bots()
                continue

            if not room.game:
                continue
            gp = room.game.get_player(player_id)
            if not gp:
                continue

            result = {"error": "неизвестное действие"}
            if action == "resolve_event":
                result = room.game.resolve_event()
            elif action == "resolve_decision":
                result = room.game.resolve_decision(gp, msg.get("option_id", ""))
            elif action == "play_card":
                result = room.game.play_card(gp, msg["card_id"], **msg.get("params", {}))
            elif action == "activate_attack":
                result = room.game.activate_attack(gp, msg["card_id"], **msg.get("params", {}))
            elif action == "activate_permanent":
                result = room.game.activate_permanent(gp, msg["card_id"], **msg.get("params", {}))
            elif action == "buy_card":
                result = room.game.buy_card(gp, msg["card_id"], msg.get("use_chipsines"))
            elif action == "buy_wild_magic":
                result = room.game.buy_wild_magic(gp)
            elif action == "buy_familiar":
                result = room.game.buy_familiar(gp, msg.get("card_id"), msg.get("use_chipsines"))
            elif action == "end_turn":
                result = room.game.end_turn(gp)

            if result.get("error"):
                await websocket.send_json({"type": "error", "message": result["error"]})
            else:
                await room.broadcast()
                await room.run_bots()
            await room.broadcast()

    except WebSocketDisconnect:
        if player_id and player_id in room.connections:
            del room.connections[player_id]
        # Игрок пропал — ставим партию на паузу и ждём его возвращения.
        if player_id and room.started and player_id in room.player_names and not room.is_bot(player_id):
            room.offline.add(player_id)
            room.log_line(f"{room.player_names[player_id]} отключился — партия на паузе")
            await room.broadcast()
        elif player_id and not room.started:
            # До старта просто убираем из лобби, чтобы не висел «призрак».
            room.player_names.pop(player_id, None)
            room.player_avatars.pop(player_id, None)
            room.selected_properties.pop(player_id, None)
            room.selected_familiars.pop(player_id, None)
            room.property_offers.pop(player_id, None)
            room.familiar_offers.pop(player_id, None)
            if room.host_id == player_id:
                humans = [p for p in room.player_names if not room.is_bot(p)]
                room.host_id = humans[0] if humans else None
            await room.broadcast_lobby()


class NoCacheStaticFiles(StaticFiles):
    """Отдаёт фронтенд без кэша.

    Причина: браузер держал в кэше старые index.html/app.js/style.css и показывал
    прошлую вёрстку планшета и нулевые счётчики стопок, хотя на диске лежал новый код.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:  # noqa: D102
        return False

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        for header in ("etag", "last-modified"):
            if header in response.headers:
                del response.headers[header]
        return response


app.mount("/", NoCacheStaticFiles(directory="frontend", html=True), name="frontend")
