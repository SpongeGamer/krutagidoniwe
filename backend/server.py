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
            selected_by_other = {fid for pid, fids in self.selected_familiars.items() if pid != player_id for fid in fids}
            reserved_by_other = {board["id"] for pid, offers in self.familiar_offers.items() if pid != player_id for board in offers}
            return [board for board in BOARDS if board["id"] not in selected_by_other and board["id"] not in reserved_by_other]
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

    async def run_bots(self):
        """Пошаговый тестовый ИИ: после каждого действия рассылает состояние.
        Поэтому человек видит карты, покупки и смену хода, а не только итог.
        """
        if not self.game:
            return
        safety = 0
        announced_bot_id: Optional[str] = None
        while safety < 200 and not self.game.game_over:
            safety += 1
            game = self.game
            if game.pending_event:
                # Беспредел человека всегда ждёт клика; бот может продолжить свой.
                if not self.is_bot(game.active_player.id):
                    break
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
                game.resolve_decision(bot, options[0]["id"])
                await self.broadcast()
                await asyncio.sleep(0.7)
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
                cid = active.hand[0]
                card = game.cards[cid]
                params = {}
                enemies = game.enemies_of(active)
                if (card.has_attack or "выбранн" in (card.full_text or "").lower()) and enemies:
                    params["target_id"] = enemies[0].id
                game.play_card(active, cid, **params)
                await self.broadcast()
                await asyncio.sleep(1.1)
                continue
            affordable = [cid for cid in game.market + game.legend_market if game.cards[cid].cost <= active.power_available]
            if affordable:
                chosen = min(affordable, key=lambda cid: game.cards[cid].cost)
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
        for pid, ws in list(self.connections.items()):
            try:
                await ws.send_json({"type": "state", "state": self.game.to_public_dict(viewer_id=pid)})
            except Exception:
                pass

    async def broadcast_lobby(self):
        players = [
            {"id": pid, "name": name, "avatar": self.player_avatars.get(pid, "🧙"),
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
        player_id = join_msg.get("player_id") or str(uuid.uuid4())[:8]
        room.connections[player_id] = websocket
        room.player_names[player_id] = name
        if room.host_id is None:
            room.host_id = player_id
        room.player_avatars[player_id] = avatar
        room.ensure_property_offer(player_id)
        await websocket.send_json({"type": "joined", "player_id": player_id})

        if room.started and room.game:
            await websocket.send_json({"type": "state", "state": room.game.to_public_dict(viewer_id=player_id)})
        else:
            await room.broadcast_lobby()

        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")

            if action == "add_bot" and not room.started:
                if player_id != room.host_id:
                    await websocket.send_json({"type": "error", "message": "Бота может добавить только хост"})
                elif not room.add_bot():
                    await websocket.send_json({"type": "error", "message": "Нельзя добавить больше ботов"})
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
                    reserved_by_other = {board["id"] for pid, offers in room.familiar_offers.items() if pid != player_id for board in offers}
                    allowed = {board["id"] for board in BOARDS if board["id"] not in reserved_by_other}
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
                    # При смене свойства сбрасываем фамильяров и выдаём новую пару.
                    room.selected_properties[player_id] = property_id
                    room.selected_familiars.pop(player_id, None)
                    room.familiar_offers.pop(player_id, None)
                    room.ensure_familiar_offer(player_id)
                else:
                    await websocket.send_json({"type": "error", "message": "Выбери одно из предложенных свойств"})
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
                result = room.game.buy_card(gp, msg["card_id"])
            elif action == "buy_wild_magic":
                result = room.game.buy_wild_magic(gp)
            elif action == "buy_familiar":
                result = room.game.buy_familiar(gp)
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
