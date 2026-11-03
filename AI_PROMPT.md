# Paste this into Cursor or Claude

Replace `YOUR-NAME` with the folder name you were given. Then let the tool edit code and run the checker. Do not paste this into the agent you submit. It is instructions for the coding tool, not for the game.

---

You are writing a Coup bot for a timed hackathon. Work only in this repository.

Edit only `agents/local/YOUR-NAME/agent.py` while iterating (gitignored). For the scored file, use `agents/submissions/YOUR-NAME/agent.py` (also gitignored — do not commit either or open a PR). Create the file by copying `agents/template/agent.py` if it does not exist. Do not modify anything under `coup/`, `tests/`, `scripts/`, or `agents/examples/`. When the organizers’ `.env` is in the repo root, submit with `python scripts/hub.py upload YOUR-NAME --full-name "…"` from the submissions copy.

Read `RULES.md` and `API.md` before you write the policy. The engine in `coup/engine/` is the referee. Do not import it. Your file may import from `coup.agent_api` and the Python standard library. It must not import `socket`, `requests`, `urllib`, `http`, `subprocess`, `importlib`, `ctypes`, or `coup.engine`. It must not print.

The class must subclass `Agent` and `__init__` must take no arguments besides `self`. Define exactly one Agent subclass in the file.

Implement:

- `choose_action(view)` returns one of `view.legal_actions`. If every legal action is a Coup, the player has 10 or more coins and must Coup.
- `respond_to_action(view, action)` checks `view.phase`. In `challenge`, return `Pass()` or `Challenge()`. In `block`, return `Pass()` or a `Block` from `view.legal_responses`. Do not challenge during the block phase. Do not block during the challenge phase.
- `respond_to_block(view, block)` returns `Pass()` or `Challenge()`.
- `choose_card_to_lose(view)` returns one of `view.your_cards`.
- `choose_exchange(view, drawn)` returns the cards to KEEP. The length must equal `len(view.your_cards)`. The pool is `list(view.your_cards) + list(drawn)`. Do not return the discards.

Use `view.your_cards`, `view.players` (coins, influence, revealed), and `view.history`. You cannot see other players' face-down cards. `on_game_start(view, seed)` may store `seed` for `random.Random`. That seed is not the deck order.

A strong simple policy, which you should then improve:

- If you must Coup, Coup the living opponent with the least influence, breaking ties toward more coins.
- If you hold the Duke, Tax.
- If you hold the Assassin, have 3 or more coins, and an opponent has 1 influence, Assassinate them.
- If you hold the Captain, Steal from the richest opponent.
- Otherwise Income.
- Block with a card only when you actually hold it.
- Challenge a claim when none of that card can still be in their hand, given your cards, revealed cards, and `view.copies_per_card`.

After each edit, run:

```powershell
python scripts/test_agent.py agents/local/YOUR-NAME/agent.py
```

Repeat until the last line is `READY`. If it says `NOT READY`, fix illegal moves, exceptions, and timeouts. Do not weaken the checker. Win rate is printed for you. It does not have to be high for `READY`, but do not stop at a bot that only takes Income if you still have time. Compare against the bots in `agents/examples/` by reading them, not by importing the engine.

When `READY` is stable, run:

```powershell
python scripts/play.py --agents agents/submissions/YOUR-NAME/agent.py,honest,bluffer,challenger --seed 1
```

Fix anything that throws. Then stop.
