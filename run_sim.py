"""Прогон партии со случайными ходами — проверка, что движок не падает."""
import random
from backend.game import GameState

random.seed(1)
game = GameState(["Аня", "Боря", "Вика"], seed=42)
game.start_turn()

MAX_TURNS = 400
turns = 0
while not game.game_over and turns < MAX_TURNS:
    turns += 1
    p = game.active_player

    # играем все карты руки без спец-параметров (примитивно, только для smoke-теста)
    for cid in list(p.hand):
        card = game.cards[cid]
        params = {}
        if card.has_attack or "выбранн" in (card.full_text or "").lower():
            enemies = game.enemies_of(p)
            if enemies:
                params["target_id"] = random.choice(enemies).id
            else:
                params["target_id"] = p.id
        game.play_card(p, cid, **params)

    # покупаем всё, что можем себе позволить, подешевле
    bought = True
    while bought and p.power_available > 0:
        bought = False
        affordable = [c for c in game.market + game.legend_market if game.cards[c].cost <= p.power_available]
        if affordable:
            cheapest = min(affordable, key=lambda c: game.cards[c].cost)
            res = game.buy_card(p, cheapest)
            if res.get("ok"):
                bought = True

    game.end_turn(p)

print(f"Симуляция остановлена после {turns} ходов. game_over={game.game_over}")
if game.game_over:
    print("Победитель:", game.get_player(game.winner).name)
    print(game.final_scores)
print("\nПоследние строки лога:")
for line in game.logs[-15:]:
    print(" ", line)
