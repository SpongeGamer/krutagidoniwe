let ws = null;
let myId = null;
let myName = null;
let roomId = null;
let lastState = null;

const $ = (id) => document.getElementById(id);

function wsUrl(room) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/${encodeURIComponent(room)}`;
}

$("join-btn").onclick = () => {
  myName = $("name-input").value.trim() || "Колдун";
  roomId = $("room-input").value.trim() || "default";
  const saved = localStorage.getItem("krutagidon_pid_" + roomId);

  ws = new WebSocket(wsUrl(roomId));
  ws.onopen = () => {
    ws.send(JSON.stringify({ name: myName, player_id: saved || undefined }));
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    handleMessage(msg);
  };
  ws.onclose = () => console.log("Соединение закрыто");
};

function handleMessage(msg) {
  if (msg.type === "joined") {
    myId = msg.player_id;
    localStorage.setItem("krutagidon_pid_" + roomId, myId);
    show("lobby-screen");
    $("lobby-room-code").textContent = roomId;
  } else if (msg.type === "lobby") {
    $("lobby-players").innerHTML = msg.players.map(n => `<li>${escapeHtml(n)}</li>`).join("");
    if (msg.started) show("game-screen");
  } else if (msg.type === "state") {
    lastState = msg.state;
    show("game-screen");
    render(msg.state);
  } else if (msg.type === "error") {
    alert(msg.message);
  }
}

function show(id) {
  ["join-screen", "lobby-screen", "game-screen"].forEach(s => $(s).classList.toggle("hidden", s !== id));
}

$("start-btn").onclick = () => ws.send(JSON.stringify({ action: "start_game" }));
$("end-turn-btn").onclick = () => ws.send(JSON.stringify({ action: "end_turn" }));
$("buy-wild-btn").onclick = () => ws.send(JSON.stringify({ action: "buy_wild_magic" }));
$("buy-familiar-btn").onclick = () => ws.send(JSON.stringify({ action: "buy_familiar" }));

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function cardEl(c, onClick) {
  const div = document.createElement("div");
  div.className = "card";
  div.title = c.text || "";
  div.innerHTML = `
    <img class="cart-img" src="cards/${encodeURIComponent(c.id)}.jpg"
         onerror="this.style.display='none'" />
    <div class="cname">${escapeHtml(c.name)}</div>
    <div class="ctext">${escapeHtml((c.text || "").slice(0, 90))}</div>
    <div class="cfooter">
      <span class="cost">💰${c.cost}</span>
      <span class="power">+${c.power}</span>
    </div>`;
  if (onClick) div.onclick = onClick;
  return div;
}

function render(state) {
  const me = state.players.find(p => p.id === myId);
  const isMyTurn = state.turn_player_id === myId;

  // лог
  $("log-panel").innerHTML = state.logs.map(l => `<div>${escapeHtml(l)}</div>`).join("");
  $("log-panel").scrollTop = $("log-panel").scrollHeight;

  // оппоненты (и я сам сверху, компактно)
  $("opponents").innerHTML = "";
  state.players.forEach(p => {
    const div = document.createElement("div");
    div.className = "opp-card" + (p.id === state.turn_player_id ? " active-turn" : "");
    div.innerHTML = `
      <div class="name">${escapeHtml(p.name)}${p.id === myId ? " (я)" : ""} ${p.controls_prize ? "👑" : ""} ${p.is_loshara ? "🤡" : ""}</div>
      <div class="stat">❤️ ${p.life}/${p.max_life}</div>
      <div class="stat">🧀 чипсины: ${p.chipsines}</div>
      <div class="stat">🎴 рука: ${p.hand_count}, колода: ${p.deck_count}, сброс: ${p.discard_count}</div>
      <div class="stat">💀 ЖДК: ${p.death_tokens}</div>
      <div class="stat">⚡ мощь: ${p.power_available}</div>
    `;
    $("opponents").appendChild(div);
  });

  // рынок
  $("main-deck-count").textContent = state.main_deck_count;
  $("legend-deck-count").textContent = state.legend_deck_count;
  $("wild-count").textContent = state.wild_magic_remaining;
  $("market").innerHTML = "";
  state.market.forEach(c => {
    $("market").appendChild(cardEl(c, () => isMyTurn && buyCard(c.id)));
  });
  $("legend-market").innerHTML = "";
  state.legend_market.forEach(c => {
    $("legend-market").appendChild(cardEl(c, () => isMyTurn && buyCard(c.id)));
  });
  $("buy-wild-btn").disabled = !isMyTurn;
  $("buy-familiar-btn").disabled = !isMyTurn || !me || me.familiar_bought;

  // моя рука
  $("hand").innerHTML = "";
  if (me && me.hand) {
    me.hand.forEach(c => {
      $("hand").appendChild(cardEl(c, () => isMyTurn && playCard(c)));
    });
  }
  $("self-stats").innerHTML = me ? `
    <b>${escapeHtml(me.name)}</b> — ❤️${me.life} | ⚡ мощь доступно: ${me.power_available} |
    🧀 чипсины: ${me.chipsines} | ${isMyTurn ? "<b style='color:#ffb84d'>ТВОЙ ХОД</b>" : "ход соперника"}
  ` : "";
  $("end-turn-btn").disabled = !isMyTurn;

  if (state.game_over) {
    const winner = state.players.find(p => p.id === state.winner);
    alert("Игра окончена! Победитель: " + (winner ? winner.name : "?"));
  }
}

function buyCard(cardId) {
  ws.send(JSON.stringify({ action: "buy_card", card_id: cardId }));
}

function playCard(card) {
  let params = {};
  if (card.text && card.text.toLowerCase().includes("выбранн")) {
    const targets = lastState.players.filter(p => p.id !== myId).map(p => `${p.name} (${p.id})`).join(", ");
    const targetId = prompt(`Карта требует цель. Введи id цели.\nВарианты: ${targets}\nСвой id: ${myId}`);
    if (targetId) params.target_id = targetId.trim();
  }
  ws.send(JSON.stringify({ action: "play_card", card_id: card.id, params }));
}
