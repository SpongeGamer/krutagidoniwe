"""
WebSocket-сервер для игры вживую с друзьями.
Никакой БД: комнаты живут в памяти процесса, пока сервер запущен.

Запуск:
    pip install -r requirements.txt
    uvicorn backend.server:app --host 0.0.0.0 --port 8000

Наружу пробрасывать через Cloudflare Tunnel / ngrok — без VPN, без открытия
портов на роутере.
"""
from __future__ import annotations
import json
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .game import GameState

app = FastAPI()


class Room:
    def __init__(self, room_id: str):
        self.id = room_id
        self.game: Optional[GameState] = None
        self.connections: dict[str, WebSocket] = {}   # player_id -> ws
        self.player_names: dict[str, str] = {}         # player_id -> name (пока лобби)
        self.started = False

    async def broadcast(self):
        if not self.game:
            return
        for pid, ws in list(self.connections.items()):
            try:
                await ws.send_json({
                    "type": "state",
                    "state": self.game.to_public_dict(viewer_id=pid),
                })
            except Exception:
                pass

    async def broadcast_lobby(self):
        for pid, ws in list(self.connections.items()):
            try:
                await ws.send_json({
                    "type": "lobby",
                    "players": list(self.player_names.values()),
                    "started": self.started,
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
        # первое сообщение — join с именем
        join_msg = await websocket.receive_json()
        name = join_msg.get("name", "Колдун")
        player_id = join_msg.get("player_id") or str(uuid.uuid4())[:8]

        room.connections[player_id] = websocket
        room.player_names[player_id] = name
        await websocket.send_json({"type": "joined", "player_id": player_id})

        if room.started and room.game:
            await websocket.send_json({
                "type": "state",
                "state": room.game.to_public_dict(viewer_id=player_id),
            })
        else:
            await room.broadcast_lobby()

        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")

            if action == "start_game":
                if not room.started:
                    names_by_pid = room.player_names
                    room.game = GameState(list(names_by_pid.values()))
                    # сопоставляем реальные player_id соединений с id внутри GameState
                    # по порядку присоединения
                    for (pid, _name), gp in zip(names_by_pid.items(), room.game.players):
                        gp.id = pid
                    room.game.turn_idx = 0
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
            if action == "play_card":
                result = room.game.play_card(gp, msg["card_id"], **msg.get("params", {}))
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
