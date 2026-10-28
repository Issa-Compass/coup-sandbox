"""Turn state machine for a single Coup game.

The runner drives this object. It never calls agents itself, so a hung agent
cannot sit inside the engine. Hidden cards stay on ``Player`` and are copied
into a redacted ``PlayerView`` only for the seat that is allowed to see them.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from coup.agent_api import (
    ACTION_COST,
    ACTION_LABEL,
    STEAL_AMOUNT,
    TURN_CAP,
    Action,
    ActionType,
    Block,
    Card,
    Challenge,
    Event,
    GameResult,
    Pass,
    Placement,
    PlayerView,
    PublicPlayer,
    Response,
    card_label,
)
from coup.engine.cards import build_deck, copies_per_card
from coup.engine.rules import (
    cards_returned,
    claim_of,
    exchange_keep_is_legal,
    legal_actions,
    legal_block_cards,
    placement_points,
    starting_coins,
)
from coup.engine.state import Player


@dataclass(frozen=True)
class Prompt:
    kind: str
    seat: int


class Game:
    def __init__(self, names: list[str], seed: int, max_turns: int = TURN_CAP):
        if not 2 <= len(names) <= 6:
            raise ValueError("Coup supports 2 to 6 players")
        if len(set(names)) != len(names):
            raise ValueError("player names must be unique")
        if max_turns < 1:
            raise ValueError("max_turns must be positive")
        self.seed = seed
        self.max_turns = max_turns
        self.rng = random.Random(seed)
        self.copies_per_card = copies_per_card(len(names))
        deck = build_deck(len(names))
        self.rng.shuffle(deck)
        coins = starting_coins(len(names))
        self.players = [
            Player(seat=index, name=name, coins=coins, cards=[deck.pop(), deck.pop()])
            for index, name in enumerate(names)
        ]
        self.deck = deck
        self.held: list[Card] = []
        self.history: list[Event] = []
        self.current = 0
        self.actor: int | None = None
        self.turns_played = 0
        self.phase = "action"
        self.pending_action: Action | None = None
        self.pending_block: Block | None = None
        self.ask_queue: list[int] = []
        self.lose_queue: list[tuple[int, str]] = []
        self.cont: str | None = None
        self.elimination_order: list[int] = []
        self.finished = False
        self.capped = False
        self.placements: tuple[Placement, ...] = ()
        self._event(
            "start",
            self._start_message(),
            turn=0,
        )
        self._begin_turn()

    def prompt(self) -> Prompt | None:
        if self.finished:
            return None
        if self.phase == "action":
            return Prompt("choose_action", self.current)
        if self.phase in ("challenge", "block"):
            return Prompt("respond_to_action", self.ask_queue[0])
        if self.phase == "challenge_block":
            return Prompt("respond_to_block", self.ask_queue[0])
        if self.phase == "lose":
            return Prompt("choose_card_to_lose", self.lose_queue[0][0])
        if self.phase == "exchange":
            if self.actor is None:
                raise RuntimeError("exchange without an actor")
            return Prompt("choose_exchange", self.actor)
        raise RuntimeError(f"unknown phase {self.phase}")

    def view_for(self, seat: int) -> PlayerView:
        you = self.players[seat]
        show_drawn = self.phase == "exchange" and seat == self.actor
        return PlayerView(
            you=seat,
            phase=self.phase,
            turn=self.turns_played,
            actor=self.actor,
            players=tuple(
                PublicPlayer(
                    seat=player.seat,
                    name=player.name,
                    coins=player.coins,
                    influence=player.influence,
                    revealed=tuple(player.revealed),
                )
                for player in self.players
            ),
            your_cards=tuple(you.cards),
            history=tuple(self.history),
            legal_actions=tuple(self._legal_actions_for(seat)),
            legal_responses=tuple(self._legal_responses_for(seat)),
            action=self.pending_action,
            block=self.pending_block,
            deck_count=len(self.deck),
            drawn=tuple(self.held) if show_drawn else (),
            copies_per_card=self.copies_per_card,
            total_cards=self.copies_per_card * len(Card),
        )

    def submit_action(self, action: Action) -> None:
        if self.phase != "action":
            raise RuntimeError(f"not waiting for an action ({self.phase})")
        if action not in self._legal_actions_for(self.current):
            raise ValueError(f"illegal action {action}")
        self.actor = self.current
        self.pending_action = action
        self.pending_block = None
        cost = ACTION_COST.get(action.type, 0)
        if cost:
            self.players[self.actor].coins -= cost
        self._event(
            "action",
            self._action_message(action, cost),
            seat=self.actor,
            target=action.target,
            action=action.type.value,
            card=claim_of(action),
            amount=cost or None,
            coins=self.players[self.actor].coins,
        )
        if claim_of(action) is not None:
            self.ask_queue = self._seats_after(self.actor)
            if not self.ask_queue:
                self._resolve_effect()
                return
            self.phase = "challenge"
            return
        self._begin_block_or_effect()

    def submit_reaction(self, response: Response) -> None:
        if self.phase == "challenge":
            self._submit_challenge(response, on_challenge=self._resolve_action_challenge)
            return
        if self.phase == "block":
            self._submit_block(response)
            return
        if self.phase == "challenge_block":
            self._submit_challenge(response, on_challenge=self._resolve_block_challenge)
            return
        raise RuntimeError(f"not waiting for a reaction ({self.phase})")

    def submit_loss(self, card: Card) -> None:
        if self.phase != "lose" or not self.lose_queue:
            raise RuntimeError("not waiting for a lost card")
        seat, reason = self.lose_queue[0]
        player = self.players[seat]
        if card not in player.cards:
            raise ValueError(f"{player.name} cannot reveal {card}")
        self.lose_queue.pop(0)
        player.cards.remove(card)
        player.revealed.append(card)
        self._event(
            "lose",
            self._loss_message(player.name, card, reason),
            seat=seat,
            card=card,
        )
        if not player.alive:
            self.elimination_order.append(seat)
            self._event("eliminate", f"{player.name} is eliminated.", seat=seat)
        self._after_loss()

    def submit_exchange(self, keep: list[Card]) -> None:
        if self.phase != "exchange" or self.actor is None:
            raise RuntimeError("not waiting for an exchange")
        player = self.players[self.actor]
        pool = player.cards + self.held
        if not exchange_keep_is_legal(list(keep), pool, len(player.cards)):
            raise ValueError("illegal exchange")
        returned = cards_returned(pool, list(keep))
        player.cards = list(keep)
        self.deck.extend(returned)
        self.rng.shuffle(self.deck)
        self.held = []
        self._event("exchange", f"{player.name} exchanges cards with the Court.", seat=player.seat)
        self._end_turn()

    def result(self) -> GameResult:
        if not self.finished:
            raise RuntimeError("game is not over")
        winner = self.placements[0].seat
        return GameResult(
            placements=self.placements,
            turns=self.turns_played,
            capped=self.capped,
            winner=winner,
        )

    def card_counts(self) -> Counter[Card]:
        counts: Counter[Card] = Counter(self.deck)
        counts.update(self.held)
        for player in self.players:
            counts.update(player.cards)
            counts.update(player.revealed)
        return counts

    def _legal_actions_for(self, seat: int) -> list[Action]:
        if self.finished or self.phase != "action" or seat != self.current:
            return []
        if not self.players[seat].alive:
            return []
        return legal_actions(self.players[seat].coins, self._seats_after(seat))

    def _legal_responses_for(self, seat: int) -> list[Response]:
        if self.finished or not self.ask_queue or self.ask_queue[0] != seat:
            return []
        if self.phase in ("challenge", "challenge_block"):
            return [Pass(), Challenge()]
        if self.phase == "block" and self.pending_action is not None:
            return [Pass(), *[Block(card) for card in legal_block_cards(self.pending_action)]]
        return []

    def _submit_challenge(self, response: Response, on_challenge) -> None:
        if not self.ask_queue:
            raise RuntimeError("nobody left to ask")
        if isinstance(response, Challenge):
            challenger = self.ask_queue[0]
            self.ask_queue.clear()
            on_challenge(challenger)
            return
        if isinstance(response, Pass):
            self.ask_queue.pop(0)
            if self.ask_queue:
                return
            if self.phase == "challenge":
                self._begin_block_or_effect()
            else:
                self._end_turn()
            return
        raise ValueError("illegal response")

    def _submit_block(self, response: Response) -> None:
        if not self.ask_queue or self.pending_action is None:
            raise RuntimeError("nobody left to block")
        seat = self.ask_queue[0]
        if isinstance(response, Block) and response.card in legal_block_cards(self.pending_action):
            self.ask_queue.clear()
            self.pending_block = Block(response.card, seat=seat)
            self._event(
                "block",
                (
                    f"{self.players[seat].name} blocks {ACTION_LABEL[self.pending_action.type]}"
                    f", claiming {card_label(response.card)}."
                ),
                seat=seat,
                action=self.pending_action.type.value,
                card=response.card,
                target=self.pending_action.target,
            )
            self.ask_queue = self._seats_after(seat)
            if not self.ask_queue:
                self._end_turn()
                return
            self.phase = "challenge_block"
            return
        if isinstance(response, Pass):
            self.ask_queue.pop(0)
            if not self.ask_queue:
                self._resolve_effect()
            return
        raise ValueError("illegal response")

    def _resolve_action_challenge(self, challenger: int) -> None:
        if self.pending_action is None or self.actor is None:
            raise RuntimeError("no action to challenge")
        claim = claim_of(self.pending_action)
        if claim is None:
            raise RuntimeError("this action cannot be challenged")
        self._resolve_claim(
            challenger=challenger,
            claimer=self.actor,
            claim=claim,
            upheld="action_claim_upheld",
            failed="action_claim_failed",
        )

    def _resolve_block_challenge(self, challenger: int) -> None:
        if self.pending_block is None or self.pending_block.seat is None:
            raise RuntimeError("no block to challenge")
        self._resolve_claim(
            challenger=challenger,
            claimer=self.pending_block.seat,
            claim=self.pending_block.card,
            upheld="block_upheld",
            failed="block_failed",
        )

    def _resolve_claim(
        self,
        challenger: int,
        claimer: int,
        claim: Card,
        upheld: str,
        failed: str,
    ) -> None:
        claim_true = claim in self.players[claimer].cards
        claimer_name = self.players[claimer].name
        challenger_name = self.players[challenger].name
        if claim_true:
            self._event(
                "challenge",
                (
                    f"{challenger_name} challenges {claimer_name}'s {card_label(claim)}. "
                    f"The claim is true."
                ),
                challenger=challenger,
                claimer=claimer,
                card=claim,
                success=False,
            )
            self._prove(claimer, claim)
            self._lose(challenger, "bad_challenge", upheld)
            return
        self._event(
            "challenge",
            (
                f"{challenger_name} challenges {claimer_name}'s {card_label(claim)}. "
                f"The claim is a bluff."
            ),
            challenger=challenger,
            claimer=claimer,
            card=claim,
            success=True,
        )
        self._lose(claimer, "bluff", failed)

    def _prove(self, seat: int, card: Card) -> None:
        player = self.players[seat]
        player.cards.remove(card)
        self.deck.append(card)
        self.rng.shuffle(self.deck)
        player.cards.append(self.deck.pop())
        self._event(
            "prove",
            (
                f"{player.name} shows {card_label(card)}, shuffles it into the deck, "
                f"and draws a replacement."
            ),
            seat=seat,
            card=card,
        )

    def _begin_block_or_effect(self) -> None:
        action = self.pending_action
        if action is None or self.actor is None:
            raise RuntimeError("no action")
        if self._alive_count() <= 1:
            self._finish(False)
            return
        if action.type in (ActionType.ASSASSINATE, ActionType.STEAL):
            target = action.target
            if target is None or not self.players[target].alive:
                self._end_turn()
                return
            self.ask_queue = [target]
            self.phase = "block"
            return
        if action.type is ActionType.FOREIGN_AID:
            self.ask_queue = self._seats_after(self.actor)
            if not self.ask_queue:
                self._resolve_effect()
                return
            self.phase = "block"
            return
        self._resolve_effect()

    def _resolve_effect(self) -> None:
        action = self.pending_action
        if action is None or self.actor is None:
            raise RuntimeError("no action")
        if action.type is ActionType.INCOME:
            self._gain(self.actor, 1, "Income")
            self._end_turn()
        elif action.type is ActionType.FOREIGN_AID:
            self._gain(self.actor, 2, "Foreign Aid")
            self._end_turn()
        elif action.type is ActionType.TAX:
            self._gain(self.actor, 3, "Tax")
            self._end_turn()
        elif action.type is ActionType.STEAL:
            self._steal(action)
        elif action.type is ActionType.EXCHANGE:
            self._begin_exchange()
        elif action.type in (ActionType.ASSASSINATE, ActionType.COUP):
            target = action.target
            if target is None or not self.players[target].alive:
                self._end_turn()
                return
            reason = "assassinate" if action.type is ActionType.ASSASSINATE else "coup"
            self._lose(target, reason, "effect_done")
        else:
            raise RuntimeError(action.type)

    def _steal(self, action: Action) -> None:
        if action.target is None or self.actor is None:
            raise RuntimeError("steal needs a target")
        target = self.players[action.target]
        if not target.alive:
            self._end_turn()
            return
        amount = min(STEAL_AMOUNT, target.coins)
        target.coins -= amount
        self.players[self.actor].coins += amount
        self._event(
            "steal",
            (
                f"{self.players[self.actor].name} steals {amount} "
                f"from {target.name}."
            ),
            seat=self.actor,
            target=target.seat,
            amount=amount,
            coins=self.players[self.actor].coins,
        )
        self._end_turn()

    def _begin_exchange(self) -> None:
        if self.actor is None:
            raise RuntimeError("exchange without an actor")
        draw_count = min(2, len(self.deck))
        self.held = [self.deck.pop() for _ in range(draw_count)]
        if not self.held or not self.players[self.actor].alive:
            self.deck.extend(self.held)
            self.rng.shuffle(self.deck)
            self.held = []
            self._end_turn()
            return
        self.phase = "exchange"

    def _gain(self, seat: int, amount: int, why: str) -> None:
        self.players[seat].coins += amount
        self._event(
            "coins",
            f"{self.players[seat].name} gains {amount} from {why}.",
            seat=seat,
            amount=amount,
            coins=self.players[seat].coins,
        )

    def _lose(self, seat: int, reason: str, cont: str) -> None:
        self.cont = cont
        if self.players[seat].alive:
            self.lose_queue.append((seat, reason))
            self.phase = "lose"
            return
        self._after_loss()

    def _after_loss(self) -> None:
        if self.lose_queue:
            self.phase = "lose"
            return
        cont = self.cont
        self.cont = None
        if cont == "action_claim_upheld":
            self._begin_block_or_effect()
        elif cont in ("action_claim_failed", "block_upheld", "effect_done"):
            self._end_turn()
        elif cont == "block_failed":
            self._resolve_effect()
        else:
            raise RuntimeError(f"unknown continuation {cont}")

    def _end_turn(self) -> None:
        self.pending_action = None
        self.pending_block = None
        self.ask_queue = []
        if self.held:
            self.deck.extend(self.held)
            self.rng.shuffle(self.deck)
            self.held = []
        if self._alive_count() <= 1:
            self._finish(False)
            return
        self.current = (self.current + 1) % len(self.players)
        self._begin_turn()

    def _begin_turn(self) -> None:
        if self.finished:
            return
        if self._alive_count() <= 1:
            self._finish(False)
            return
        guard = 0
        while not self.players[self.current].alive:
            self.current = (self.current + 1) % len(self.players)
            guard += 1
            if guard > len(self.players):
                self._finish(False)
                return
        if self.turns_played >= self.max_turns:
            self._finish(True)
            return
        self.turns_played += 1
        self.phase = "action"
        self.actor = self.current
        self.pending_action = None
        self.pending_block = None
        self.ask_queue = []

    def _finish(self, capped: bool) -> None:
        if self.finished:
            return
        self.finished = True
        self.capped = capped
        self.phase = "done"
        self.ask_queue = []
        self.lose_queue = []
        self.placements = tuple(self._rank())
        if capped:
            self._event("turn_cap", "The turn limit is reached. Players still in are ranked by influence, then coins.")
        winner = self.placements[0]
        self._event("winner", f"{winner.name} takes 1st place.", seat=winner.seat)

    def _rank(self) -> list[Placement]:
        survivors = [player for player in self.players if player.alive]
        survivors.sort(key=lambda player: (-player.influence, -player.coins, player.seat))
        eliminated_at = {seat: index for index, seat in enumerate(self.elimination_order)}
        eliminated = [player for player in self.players if not player.alive]
        missing = [player.seat for player in eliminated if player.seat not in eliminated_at]
        if missing:
            raise RuntimeError(f"eliminated seats missing from the order: {missing}")
        eliminated.sort(key=lambda player: -eliminated_at[player.seat])
        ordered = survivors + eliminated
        count = len(self.players)
        ranked: list[Placement] = []
        for place, player in enumerate(ordered, start=1):
            ranked.append(
                Placement(
                    seat=player.seat,
                    name=player.name,
                    place=place,
                    points=placement_points(place, count),
                    influence=player.influence,
                    coins=player.coins,
                )
            )
        return ranked

    def _alive_count(self) -> int:
        return sum(1 for player in self.players if player.alive)

    def _seats_after(self, start: int) -> list[int]:
        count = len(self.players)
        seats: list[int] = []
        index = (start + 1) % count
        for _ in range(count - 1):
            if self.players[index].alive:
                seats.append(index)
            index = (index + 1) % count
        return seats

    def _event(self, event_type: str, message: str, turn: int | None = None, **data) -> None:
        self.history.append(
            Event(
                type=event_type,
                message=message,
                turn=self.turns_played if turn is None else turn,
                **data,
            )
        )

    def _start_message(self) -> str:
        names = ", ".join(player.name for player in self.players)
        coins = self.players[0].coins
        copies = self.copies_per_card
        return (
            f"New game. Players: {names}. "
            f"Each player starts with {coins} coins and 2 influence. "
            f"The deck has {copies} of each character."
        )

    def _action_message(self, action: Action, cost: int) -> str:
        if self.actor is None:
            raise RuntimeError("action without an actor")
        name = self.players[self.actor].name
        label = ACTION_LABEL[action.type]
        target = ""
        if action.target is not None:
            target = f" against {self.players[action.target].name}"
        claim = claim_of(action)
        claim_text = f", claiming {card_label(claim)}" if claim is not None else ""
        paid = f", paying {cost}" if cost else ""
        return f"{name} plays {label}{target}{claim_text}{paid}."

    @staticmethod
    def _loss_message(name: str, card: Card, reason: str) -> str:
        shown = card_label(card)
        if reason == "bluff":
            return f"{name} is caught bluffing and reveals {shown}."
        if reason == "bad_challenge":
            return f"{name}'s challenge fails and {name} reveals {shown}."
        if reason == "coup":
            return f"{name} loses an influence to the Coup: {shown}."
        if reason == "assassinate":
            return f"{name} loses an influence to the Assassination: {shown}."
        return f"{name} reveals {shown}."
