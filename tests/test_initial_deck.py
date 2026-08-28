"""Старт партии: пять карт на руке и пять в личной колоде."""
import unittest
from backend.game import GameState


class InitialDeckTests(unittest.TestCase):
    def test_each_player_starts_with_five_hand_and_five_deck(self):
        game = GameState(["А", "Б", "В"], seed=42)
        for player in game.players:
            self.assertEqual(len(player.hand), 5)
            self.assertEqual(len(player.deck), 5)
            self.assertEqual(len(player.discard), 0)


if __name__ == "__main__":
    unittest.main()
