"""Регрессия: сыгранные карты не должны клонироваться в сбросе."""
from collections import Counter
import unittest

from backend.game import GameState


class CardConservationTests(unittest.TestCase):
    def test_starter_deck_remains_ten_cards_after_a_turn_cycle(self):
        game = GameState(["А", "Б"], seed=7)
        game.start_turn()
        first = game.active_player
        initial = Counter(first.deck + first.hand)
        self.assertEqual(initial, Counter({"start_znak": 6, "start_pshik": 3, "start_syrpal": 1}))

        for card_id in list(first.hand):
            game.play_card(first, card_id, defer_attack=True)
        game.end_turn(first)

        second = game.active_player
        for card_id in list(second.hand):
            game.play_card(second, card_id, defer_attack=True)
        game.end_turn(second)

        final = Counter(first.deck + first.hand + first.discard + first.zone_in_play + first.in_play_this_turn)
        self.assertEqual(final, initial)


if __name__ == "__main__":
    unittest.main()
