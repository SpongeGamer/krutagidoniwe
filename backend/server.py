"""FastAPI + WebSocket сервер для комнат Крутагидона."""
from __future__ import annotations
import json
import os
import random
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .game import GameState
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
                    room.game.start_turn()
                    room.started = True
                    room.game.log("Игра началась!")
                    await room.broadcast()
                continue

            if not room.game:
                continue
            gp = room.game.get_player(player_id)
            if not gp:
                continue

            result = {"error": "неизвестное действие"}
            if action == "resolve_decision":
                result = room.game.resolve_decision(gp, msg.get("option_id", ""))
            elif action == "play_card":
                result = room.game.play_card(gp, msg["card_id"], **msg.get("params", {}))
            elif action == "activate_attack":
                result = room.game.activate_attack(gp, msg["card_id"], **msg.get("params", {}))
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
            await room.broadcast()

    except WebSocketDisconnect:
        if player_id and player_id in room.connections:
            del room.connections[player_id]


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
