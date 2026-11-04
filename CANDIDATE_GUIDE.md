# Candidate guide

You have the same rules as everyone else. Build an agent that wins Coup. The code around the agent is already written. This repo is public; your `agent.py` stays on your machine until you upload it to the hub.

## What to hand in

One file on disk:

```text
agents/submissions/<your-name>/agent.py
```

That folder is **gitignored**. Do not open a pull request with your bot. When you have a coup-master `.env` (URL + API key), submit with:

```bash
python scripts/hub.py upload <your-name> --full-name "Your Full Name"
```

`<your-name>` is the name on the scoreboard. Use letters, digits, underscore, and hyphen. A real full name (at least two words) is required for upload: letters, spaces, apostrophes, and hyphens only — no digits in the full name.

Do not edit the engine, the examples, or someone else's folder. Do not add dependencies. The standard library and `coup.agent_api` are enough.

## How to work

1. Follow the start steps in `README.md` until `agents/template/agent.py` prints `READY`.
2. Copy that file into your folder and rename the class if you want. The folder name is what matters.
3. Read `RULES.md` once. Then keep `API.md` open.
4. Run `python scripts/test_agent.py agents/submissions/<your-name>/agent.py` after each change. Stop when it says `READY`.
5. Watch a game: `python scripts/play.py --agents your-name,honest,guard,turtle,greedy --seed 1`.
6. When you have a coup-master `.env`, upload with `scripts/hub.py` (see above) or the dashboard Submit modal. Re-upload with the same browser/`player_uid` replaces your one hub entry.

If you want Cursor or Claude to write the first version, paste `AI_PROMPT.md` and put your folder name in the blank.

## What "good" looks like

`READY` is the minimum. It means you never return an illegal move, throw, or run past 1 second.

The example bots are the ladder (shared foundation + tendency knobs in
`agents/examples/foundation.py`):

- `random` mostly picks legal moves at random, with survival floors (card-count
  impossibles, last-life Contessa). Beat this first.
- `honest` is mostly truthful: rare light bluffs, survival Contessa, and challenges only soft claims.
- `guard` Steals and Cap/Amb-blocks forever (steallock).
- `turtle` Taxes with Duke otherwise Incomes; almost never FA/Steal.
- `greedy` runs an FA + Steal economy (Tax if it holds Duke).
- Also shipped: `bluffer` (Tax/Assassin liar) and `challenger` (soft-claim caller).

You can read their source. Copying an example and changing one number is allowed and will not win a tournament by itself.

The scoreboard uses the points in `RULES.md`, not raw wins. At a 6-player table, 1st is worth 6 points (`n` at an `n`-player table) and 2nd is worth 3. A bot that always comes second still beats a bot that wins rarely and otherwise comes last.

## Decisions you will actually write

`choose_action` is your turn. If `view.legal_actions` is only Coups, you have 10 or more coins and you must Coup.

`respond_to_action` is two different questions. Check `view.phase`:

- `challenge` means "do you call their bluff?". Return `Pass()` or `Challenge()`.
- `block` means "do you block?". Return `Pass()` or `Block(card)` for a card in `view.legal_responses`.

`respond_to_block` means "do you challenge the block?". `Pass()` or `Challenge()`.

`choose_exchange` returns the cards you keep, not the cards you throw away. This is the mistake that fails the checker most often.

## Clock and memory

A decision that takes more than 1 second is thrown away and counts as a timeout. In the tournament the process is killed, so an infinite loop does not freeze the round. You lose whatever you had stored in `self`.

You can store notes on `self` during a game, and across games in the tournament. The view on each call is complete. You do not need to reconstruct coins from the history, but the history is how you know who has been lying.

In a tournament, every seat’s `PublicPlayer.name` (and standings `name`) is an opaque UID that stays fixed for the whole run. You are not told the submission names — guess from play style, and reuse the UID to connect the same opponent across games.

In a tournament round you may optionally call `query_standings(StandingsScope.TABLE|ROUND|TOURNAMENT)` or `query_previous_round_winners()` from `coup.agent_api` to see public placement points so far. Single `play.py` games and the checker leave those as `None`.

Do not print. Do not open `results/` files. Do not call an LLM from the agent. The model, if you use one, is for writing the code before the game.

## Getting unstuck

`READY` means you can submit to the hub.

`NOT READY` prints the reason.

- `import of socket is not allowed` or `only coup.agent_api may be imported`: delete that import. Reading the engine from your agent is not a legal strategy.
- `define exactly one Agent subclass`: one class in the file. A helper class that does not subclass `Agent` is fine.
- `illegal` greater than 0: you returned something that was not in `legal_actions` or `legal_responses`, or your exchange list was the wrong length. Print is banned, so write the failing case down from the checker output and compare it with `API.md`.
- `errors` greater than 0: your method raised. A sandbox line in the output includes the traceback.
- `timeouts` greater than 0: that method took more than 1 second. The usual cause is an unbounded loop.

`python scripts/play.py --reveal --seed 1` shows hidden cards after the game so you can see why a line of the log happened. That flag is for you, locally. The tournament does not give you those cards.
