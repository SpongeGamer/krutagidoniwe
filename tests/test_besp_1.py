"""Беспредел 1: урон равен максимальной стоимости ОДНОЙ карты на руке."""
import unittest
from backend.game import GameState


class BespOneTests(unittest.TestCase):
    def test_damage_is_maximum_single_hand_card_cost(self):
        game = GameState(["А", "Б"], seed=1)
        game.start_turn()
        attacker, target = game.players
        attacker.hand = ["start_pshik"]
        target.hand = ["treas_chipsalochka"]  # стоимость 3
        game._resolve_besp(game.cards["besp_1"])
        self.assertEqual(target.life, 17)


if __name__ == "__main__":
    unittest.main()
