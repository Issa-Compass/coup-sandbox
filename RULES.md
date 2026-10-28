# Coup rules

This is the base game. No Inquisitor and no Reformation. The hackathon uses **3 to 6 players**. The engine can also play 2, using the variant below. If the rulebook and this file disagree, this file wins, and `tests/test_engine.py` is the check.

## Setup

There are five characters, with **3 copies** of each (15 cards):

| Character | Action you can claim | What you can block |
| --- | --- | --- |
| Duke | Tax | Foreign Aid |
| Assassin | Assassinate | nothing |
| Captain | Steal | Steal |
| Ambassador | Exchange | Steal |
| Contessa | nothing | Assassinate |

Each player starts with **2 coins** and **2 face-down cards** (influence). Cards you still hold are secret. Cards you lose stay face up. The bank does not run out.

Seat 0 takes the first turn, then play goes clockwise. Players with no influence left are skipped. A game lasts at most **200 turns**. One turn is one player's attempt to act.

## Actions

On your turn you must play one legal action. If you have **10 or more coins**, the only legal action is Coup.

| Action | Cost | Effect | Challenged? | Blocked by |
| --- | --- | --- | --- | --- |
| Income | 0 | Take 1 coin | No | Nobody |
| Foreign Aid | 0 | Take 2 coins | No | Duke, any other living player |
| Coup | 7, paid immediately | Target loses one influence | No | Nobody |
| Tax | 0 | Claim Duke. Take 3 coins | Yes | Nobody |
| Assassinate | 3, paid immediately, **not refunded** | Claim Assassin. Target loses one influence | Yes | Contessa, the target only |
| Steal | 0 | Claim Captain. Take 2 coins from the target, or all of them if they have fewer | Yes | Captain or Ambassador, the target only |
| Exchange | 0 | Claim Ambassador. Draw 2 cards, then put cards back so you still have the same number of influence | Yes | Nobody |

You cannot target yourself. You can Steal from a player who has 0 coins; you gain 0. Coup requires 7 coins. Assassinate requires 3, and you must still have them after any earlier payment. At 10 or more coins you cannot Income, Tax, Steal, Exchange, take Foreign Aid, or Assassinate.

## Claims, challenges, and blocks

Income, Foreign Aid, and Coup do not claim a character. The other four actions do.

1. You declare the action and pay any cost.
2. If the action claims a character, the other living players are asked in seat order, starting with the player after you. The first player who challenges is the challenger. Players after them are not asked.
3. If the claim was **true**, you show that card, shuffle it into the deck, and draw a replacement. You do not lose influence. The challenger loses one influence. The action continues.
4. If the claim was **false**, the action is cancelled. You lose one influence. A cost you already paid is not returned.
5. If the action is still on, and it can be blocked, the players who are allowed to block are asked in seat order. The first legal block is the block. One block is enough.
6. The other living players, starting after the blocker, may challenge the block. Same truth rules as above. If the block was a bluff, the blocker loses one influence **and the action still happens**. If the block was true, or nobody challenges it, the action is cancelled. Paid coins stay paid.

Foreign Aid skips step 2, because it makes no claim, and goes straight to blocks. Any other living player may block it.

Assassinate and Steal ask only the target whether they block. If that target is already out, the action ends.

A failed Contessa block is the harsh case: the target loses one card for the lie, and if they are still in the game they lose another card to the assassination.

## Losing influence and winning

When you lose influence you choose which of your face-down cards to reveal. It stays face up. At zero face-down cards you are eliminated.

The last player with influence wins.

If the turn limit is reached, players still in the game rank above everyone who was eliminated. They are ordered by influence (more is better), then coins (more is better), then seat (lower seat is better). Eliminated players are ordered by who was eliminated later (later is better).

## Exchange, precisely

You draw up to 2 cards. You will be shown those cards. Return the cards you **keep**. The length of that list must equal the number of face-down cards you had before the draw. Everything you do not keep is shuffled back into the deck. With 1 influence you draw 2, keep 1, and return 2.

If the deck somehow has fewer than 2 cards, you draw what is left. In a normal 3 to 6 player game the deck is not empty.

## Two-player variant

Not used at the hackathon. With exactly 2 players the deck has 2 copies of each character, and each player starts with 1 coin. Everything else is the same.

## Tournament scoring

Each game gives placement points. In an `n`-player game, 1st place gets `n - 1` points. Place `p` after that gets `max(n - p - 1, 0)`.

| Players | 1st | 2nd | 3rd | 4th | 5th | 6th |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 6 | 5 | 3 | 2 | 1 | 0 | 0 |
| 5 | 4 | 2 | 1 | 0 | 0 | |
| 4 | 3 | 1 | 0 | 0 | | |
| 3 | 2 | 0 | 0 | | | |

The leaderboard sorts by average points per game, then win rate, then fewer illegal moves, errors, and timeouts, then name.

Tables are 4, 5, or 6 players when the field can be split that way. A field of 7 is a table of 4 and a table of 3, because everyone plays the same number of games. Seats are shuffled.

## Defaults and the clock

Each decision has a **1 second** limit in the tournament. The process is killed and the decision becomes a default:

- action: Income, or the first legal action if you must Coup
- challenge or block: Pass
- losing a card: your first face-down card
- exchange: keep the cards you already had

An illegal return or an exception uses the same default. All three are counted on the leaderboard. `test_agent.py` is not ready to submit until all three are zero.

After a timeout the process restarts and `on_game_start` runs again with the opening view. Trust the view passed into each decision, not a view you saved at the start of the game.

## What you are not allowed to do

Your agent may import `coup.agent_api` and the normal standard library. It may not import `coup.engine`, `coup.runner`, `socket`, `requests`, `urllib`, `http`, `subprocess`, `importlib`, or `ctypes`. It may not call `__import__`.

The seed passed to `on_game_start` is only for your random number generator. It is not the deck seed. Do not try to read the tournament process, the results files, or other people's agents to learn hidden cards. That is a disqualification, not a clever strategy.

Do not print from the agent. Printing does not reach you in a useful way, and enough of it can make you miss the clock.
