"""Rules the engine must implement. These are the source of truth next to RULES.md."""

from __future__ import annotations

import json
import random
from collections import Counter

import pytest

from coup.agent_api import Action, ActionType, Block, Card, Challenge, Pass
from coup.engine.game import Game
from coup.engine.rules import placement_points
from coup.serialize import from_data, to_data


def _autoplay(game: Game, seed: int) -> None:
    rng = random.Random(seed)
    while not game.finished:
        prompt = game.prompt()
        assert prompt is not None
        view = game.view_for(prompt.seat)
        if prompt.kind == "choose_action":
            game.submit_action(rng.choice(list(view.legal_actions)))
        elif prompt.kind in ("respond_to_action", "respond_to_block"):
            game.submit_reaction(rng.choice(list(view.legal_responses)))
        elif prompt.kind == "choose_card_to_lose":
            game.submit_loss(rng.choice(list(view.your_cards)))
        elif prompt.kind == "choose_exchange":
            pool = list(view.your_cards) + list(view.drawn)
            rng.shuffle(pool)
            game.submit_exchange(pool[: len(view.your_cards)])
        else:
            raise AssertionError(prompt.kind)


def test_opening_deal_for_three_and_two_players():
    game = Game(["a", "b", "c"], seed=1)
    assert [player.coins for player in game.players] == [2, 2, 2]
    assert game.copies_per_card == 3
    assert game.card_counts() == Counter({card: 3 for card in Card})
    assert all(player.influence == 2 for player in game.players)

    duel = Game(["a", "b"], seed=1)
    assert [player.coins for player in duel.players] == [1, 1]
    assert duel.copies_per_card == 2
    assert duel.card_counts() == Counter({card: 2 for card in Card})


def test_same_seed_deals_the_same_hands():
    first = Game(["a", "b", "c"], seed=99)
    second = Game(["a", "b", "c"], seed=99)
    assert [player.cards for player in first.players] == [player.cards for player in second.players]
    assert first.deck == second.deck


def test_income_and_turn_order():
    game = Game(["a", "b", "c"], seed=1)
    game.submit_action(Action(ActionType.INCOME))
    assert game.players[0].coins == 3
    assert game.current == 1
    assert game.phase == "action"


def test_foreign_aid_pays_two_when_nobody_blocks():
    game = Game(["a", "b", "c"], seed=1)
    game.submit_action(Action(ActionType.FOREIGN_AID))
    assert game.phase == "block"
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    assert game.players[0].coins == 4


def test_uncontested_duke_block_stops_foreign_aid():
    game = Game(["a", "b", "c"], seed=1)
    game.submit_action(Action(ActionType.FOREIGN_AID))
    game.submit_reaction(Block(Card.DUKE))
    assert game.phase == "challenge_block"
    assert game.prompt().seat == 2
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    assert game.players[0].coins == 2


def test_failed_block_lets_foreign_aid_through_and_costs_a_card():
    game = Game(["a", "b", "c"], seed=1)
    game.players[1].cards = [Card.CONTESSA, Card.CAPTAIN]
    game.submit_action(Action(ActionType.FOREIGN_AID))
    game.submit_reaction(Block(Card.DUKE))
    game.submit_reaction(Pass())
    game.submit_reaction(Challenge())
    assert game.prompt().seat == 1
    game.submit_loss(Card.CONTESSA)
    assert game.players[0].coins == 4
    assert Card.CONTESSA in game.players[1].revealed


def test_true_block_costs_the_challenger_and_pays_nothing():
    game = Game(["a", "b", "c"], seed=1)
    game.players[1].cards = [Card.DUKE, Card.CAPTAIN]
    game.submit_action(Action(ActionType.FOREIGN_AID))
    game.submit_reaction(Block(Card.DUKE))
    game.submit_reaction(Pass())
    game.submit_reaction(Challenge())
    assert any(event.type == "prove" and event.card is Card.DUKE for event in game.history)
    assert game.prompt().seat == 0
    game.submit_loss(game.players[0].cards[0])
    assert game.players[0].coins == 2
    assert game.players[1].influence == 2


def test_tax_bluff_is_caught_by_the_first_challenger_only():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].cards = [Card.CONTESSA, Card.CAPTAIN]
    game.submit_action(Action(ActionType.TAX))
    assert game.prompt().seat == 1
    game.submit_reaction(Challenge())
    assert game.prompt().kind == "choose_card_to_lose"
    assert game.prompt().seat == 0
    game.submit_loss(Card.CONTESSA)
    assert game.players[0].coins == 2
    assert game.players[0].influence == 1


def test_true_tax_claim_replaces_the_card_and_pays_three():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].cards = [Card.DUKE, Card.CAPTAIN]
    game.submit_action(Action(ActionType.TAX))
    assert game.players[0].coins == 2
    game.submit_reaction(Challenge())
    assert game.players[0].influence == 2
    assert any(event.type == "prove" for event in game.history)
    assert game.prompt().seat == 1
    game.submit_loss(game.players[1].cards[0])
    assert game.players[0].coins == 5
    assert game.players[1].influence == 1


def test_forced_coup_at_ten_coins_and_coup_cannot_be_blocked():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].coins = 10
    legal = game.view_for(0).legal_actions
    assert legal
    assert {action.type for action in legal} == {ActionType.COUP}
    assert all(action.target != 0 for action in legal)
    with pytest.raises(ValueError):
        game.submit_action(Action(ActionType.INCOME))
    game.submit_action(legal[0])
    assert game.players[0].coins == 3
    assert game.prompt().kind == "choose_card_to_lose"
    assert game.prompt().seat == legal[0].target


def test_coup_and_assassinate_require_coins():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].coins = 6
    kinds = {action.type for action in game.view_for(0).legal_actions}
    assert ActionType.COUP not in kinds
    assert ActionType.ASSASSINATE in kinds
    game.players[0].coins = 2
    kinds = {action.type for action in game.view_for(0).legal_actions}
    assert ActionType.ASSASSINATE not in kinds
    assert ActionType.INCOME in kinds


def test_assassinate_is_not_refunded_when_the_claim_is_a_bluff():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].coins = 5
    game.players[0].cards = [Card.DUKE, Card.CAPTAIN]
    target_cards = list(game.players[1].cards)
    game.submit_action(Action(ActionType.ASSASSINATE, target=1))
    assert game.players[0].coins == 2
    game.submit_reaction(Challenge())
    game.submit_loss(game.players[0].cards[0])
    assert game.players[0].coins == 2
    assert game.players[1].cards == target_cards


def test_lying_about_contessa_then_still_loses_to_the_assassination():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].coins = 5
    game.players[0].cards = [Card.ASSASSIN, Card.DUKE]
    game.players[1].cards = [Card.CAPTAIN, Card.AMBASSADOR]
    game.submit_action(Action(ActionType.ASSASSINATE, target=1))
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    assert game.phase == "block"
    game.submit_reaction(Block(Card.CONTESSA))
    game.submit_reaction(Pass())
    game.submit_reaction(Challenge())
    assert game.prompt().seat == 1
    game.submit_loss(Card.CAPTAIN)
    assert game.players[1].influence == 1
    assert game.prompt().kind == "choose_card_to_lose"
    game.submit_loss(Card.AMBASSADOR)
    assert not game.players[1].alive
    assert game.players[0].coins == 2


def test_contessa_block_cancels_assassination_but_keeps_the_coins():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].coins = 5
    game.players[0].cards = [Card.ASSASSIN, Card.DUKE]
    game.players[1].cards = [Card.CONTESSA, Card.CAPTAIN]
    game.submit_action(Action(ActionType.ASSASSINATE, target=1))
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    game.submit_reaction(Block(Card.CONTESSA))
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    assert game.players[1].influence == 2
    assert game.players[0].coins == 2
    assert game.current == 1


def test_steal_takes_two_or_whatever_is_left():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].cards = [Card.CAPTAIN, Card.DUKE]
    game.players[1].coins = 1
    game.submit_action(Action(ActionType.STEAL, target=1))
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    assert game.players[1].coins == 0
    assert game.players[0].coins == 3

    broke = Game(["a", "b", "c"], seed=2)
    broke.players[1].coins = 0
    broke.players[0].cards = [Card.CAPTAIN, Card.DUKE]
    broke.submit_action(Action(ActionType.STEAL, target=1))
    broke.submit_reaction(Pass())
    broke.submit_reaction(Pass())
    broke.submit_reaction(Pass())
    assert broke.players[1].coins == 0
    assert broke.players[0].coins == 2


def test_ambassador_or_captain_can_block_steal():
    game = Game(["a", "b", "c"], seed=1)
    before = game.players[0].coins
    game.submit_action(Action(ActionType.STEAL, target=1))
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    game.submit_reaction(Block(Card.AMBASSADOR))
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    assert game.players[0].coins == before


def test_exchange_keeps_the_declared_hand_and_conserves_the_deck():
    game = Game(["a", "b", "c"], seed=4)
    game.submit_action(Action(ActionType.EXCHANGE))
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    assert game.phase == "exchange"
    assert len(game.view_for(0).drawn) == 2
    assert game.view_for(1).drawn == ()
    kept = list(game.players[0].cards)
    game.submit_exchange(kept)
    assert game.players[0].cards == kept
    assert game.card_counts() == Counter({card: 3 for card in Card})


def test_exchange_with_one_influence_keeps_one_card():
    game = Game(["a", "b", "c"], seed=4)
    game.players[0].cards = [Card.AMBASSADOR]
    deck_before = len(game.deck)
    game.submit_action(Action(ActionType.EXCHANGE))
    game.submit_reaction(Pass())
    game.submit_reaction(Pass())
    assert len(game.held) == 2
    game.submit_exchange([Card.AMBASSADOR])
    assert game.players[0].cards == [Card.AMBASSADOR]
    assert len(game.deck) == deck_before


def test_failed_exchange_claim_does_not_draw():
    game = Game(["a", "b", "c"], seed=4)
    game.players[0].cards = [Card.DUKE, Card.DUKE]
    hand = list(game.players[0].cards)
    game.submit_action(Action(ActionType.EXCHANGE))
    game.submit_reaction(Challenge())
    game.submit_loss(Card.DUKE)
    assert game.players[0].cards == [Card.DUKE]
    assert game.held == []
    assert hand[0] is Card.DUKE


def test_eliminated_player_is_skipped_and_last_player_wins():
    game = Game(["a", "b"], seed=1)
    game.players[0].coins = 7
    game.players[1].cards = [Card.CONTESSA]
    game.submit_action(Action(ActionType.COUP, target=1))
    game.submit_loss(Card.CONTESSA)
    assert game.finished
    result = game.result()
    assert result.winner == 0
    assert result.place_of(0) == 1
    assert result.place_of(1) == 2
    assert result.placements[0].points == 1


def test_dead_player_does_not_take_a_turn():
    game = Game(["a", "b", "c"], seed=1)
    game.players[0].coins = 7
    game.players[1].cards = [Card.DUKE]
    game.submit_action(Action(ActionType.COUP, target=1))
    game.submit_loss(Card.DUKE)
    assert not game.players[1].alive
    assert game.current == 2
    assert game.phase == "action"


def test_turn_cap_ranks_survivors_by_influence_then_coins_then_seat():
    game = Game(["a", "b", "c"], seed=1, max_turns=3)
    for _ in range(3):
        game.submit_action(Action(ActionType.INCOME))
    assert game.finished and game.capped
    assert [item.seat for item in game.result().placements] == [0, 1, 2]
    assert [item.coins for item in game.result().placements] == [3, 3, 3]
    assert [item.points for item in game.result().placements] == [2, 0, 0]


def test_six_player_points_match_the_event_table():
    assert [placement_points(place, 6) for place in range(1, 7)] == [5, 3, 2, 1, 0, 0]
    assert [placement_points(place, 5) for place in range(1, 6)] == [4, 2, 1, 0, 0]
    assert [placement_points(place, 4) for place in range(1, 5)] == [3, 1, 0, 0]


def test_random_games_conserve_cards_and_replay():
    def messages(seed: int) -> list[str]:
        game = Game(["a", "b", "c", "d"], seed=seed, max_turns=40)
        _autoplay(game, seed=0)
        assert game.card_counts() == Counter({card: 3 for card in Card})
        return [event.message for event in game.history]

    assert messages(123) == messages(123)
    assert messages(123) != messages(124)


def test_many_random_games_conserve_the_deck():
    for seed in range(20):
        game = Game(["a", "b", "c", "d", "e"], seed=seed, max_turns=80)
        _autoplay(game, seed=seed + 9)
        assert game.card_counts() == Counter({card: 3 for card in Card})
        assert game.finished


def test_view_hides_other_players_cards():
    game = Game(["a", "b", "c"], seed=0)
    game.players[0].cards = [Card.ASSASSIN, Card.ASSASSIN]
    game.players[1].cards = [Card.DUKE, Card.DUKE]
    game.players[2].cards = [Card.CONTESSA, Card.CAPTAIN]
    game.deck = [
        Card.AMBASSADOR,
        Card.AMBASSADOR,
        Card.AMBASSADOR,
        Card.CONTESSA,
        Card.CONTESSA,
        Card.CAPTAIN,
        Card.CAPTAIN,
        Card.DUKE,
        Card.ASSASSIN,
    ]
    view = game.view_for(1)
    assert view.your_cards == (Card.DUKE, Card.DUKE)
    blob = json.dumps(to_data(view))
    assert "assassin" not in blob
    assert from_data(to_data(view)) == view


def test_player_view_round_trip():
    game = Game(["a", "b", "c"], seed=3)
    game.submit_action(Action(ActionType.INCOME))
    view = game.view_for(1)
    assert from_data(to_data(view)) == view
