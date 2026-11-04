# Coup sandbox

Sandbox for writing a Python agent that plays [Coup](https://boardgamegeek.com/boardgame/131357/coup). The engine, the rules, and the opponents are already here. You only edit your agent.

You need Python 3.11 or newer. Work through the path below in order.

## 1. Quick start (dashboard)

Creates `.venv` if needed, installs `requirements.txt`, and serves the dashboard.

macOS / Linux:

```bash
./start.sh
```

Windows (PowerShell):

```powershell
.\start.ps1
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Leave this running in a terminal. After you add or rename an agent folder, restart the server so **Local** refreshes. Optional: `PORT=9000 ./start.sh`.

No `.env` needed for local play, tournaments, or watch. Submit stays disabled until you have a coup-master `.env` (URL + API key) from whoever runs the hub.

## 2. Setup (manual / CLI)

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/test_agent.py agents/template/agent.py
python scripts/play.py --seed 1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/test_agent.py agents/template/agent.py
python scripts/play.py --seed 1
```

`READY` means the template plays legal moves. It does not mean it plays well. Keep the venv activated for every command below (or use `./start.sh` / `.\start.ps1` for the dashboard).

## 3. Baseline tournament (example bots)

(If you used `./start.sh` only, activate the venv first: `source .venv/bin/activate` / `.venv\Scripts\activate`.)

Smoke-test the shipped ladder (`random`, `honest`, `guard`, `turtle`, `greedy`) with no custom code:

```bash
python scripts/tournament.py --round 1 --games-per-agent 4 --no-sandbox --run-id examples-demo --force
```

In the dashboard: open run `examples-demo` → **Standings** / **Games** → **Watch**. Playback speed and **Reveal cards** are on the watch view.

## 4. Play a manual game

In the dashboard menu: **Play Games** → **Play manually**. Pick opponent bots (examples and anything under **Local**), then **Play**. You are one seat; the others are agents. Use the on-screen actions when it is your turn.

## 5. Add a custom local agent (Cursor / Claude Code / Codex / …)

Scratch bots live under `agents/local/` (**gitignored** — never commit them).

```bash
mkdir -p agents/local/your-name
cp agents/template/agent.py agents/local/your-name/agent.py
```

Windows: `mkdir agents\local\your-name` then `copy agents\template\agent.py agents\local\your-name\agent.py`.

Use lowercase letters, digits, underscore, and hyphen in `your-name`. That string is the agent id in `--agents` and the dashboard.

To have an AI editor write the policy: open the repo in Cursor, Claude Code, Codex, or similar, paste [`AI_PROMPT.md`](AI_PROMPT.md), and tell it the folder name (`your-name`). Point it at `agents/local/your-name/agent.py` (or `agents/submissions/…` if you prefer to build the scored file from the start). The model writes code offline; the agent itself must not call an LLM at play time.

Then check:

```bash
python scripts/test_agent.py agents/local/your-name/agent.py
```

Stop when it prints `READY`. Skim [`RULES.md`](RULES.md) once; keep [`API.md`](API.md) open while you edit. More local-agent notes: [`agents/local/README.md`](agents/local/README.md).

## 6. Test your agent in a tournament

```bash
python scripts/play.py --agents your-name,honest,guard,turtle,greedy --seed 1
python scripts/tournament.py --round 1 --agents your-name random honest guard turtle greedy --games-per-agent 4 --no-sandbox --run-id local-demo --force
```

Or in the dashboard: **Play Games** → **Local** → add your agent (or **Add all**) with the examples → run a session → **Games** → **Watch**.

Edit `agents/local/your-name/agent.py`, re-run `test_agent.py`, then tournament again until you like it.

## 7. Submit your agent

Scored hand-in is **hub upload**, not a GitHub PR. `agents/submissions/` is also gitignored.

1. Copy your bot into the submissions folder (same name you want on the leaderboard):

```bash
mkdir -p agents/submissions/your-name
cp agents/local/your-name/agent.py agents/submissions/your-name/agent.py
python scripts/test_agent.py agents/submissions/your-name/agent.py
```

2. Put a coup-master `.env` in the repo root (URL + API key; see [`.env.example`](.env.example)).

3. Upload:

```bash
python scripts/hub.py upload your-name --full-name "Ada Lovelace"
```

A real full name (at least two words) is required: letters, spaces, apostrophes, and hyphens only — no digits. The **Coup AI** name (`your-name`) uses `A–Z a–z 0–9 _ -` only. Re-upload replaces your hub entry. `scripts/hub.py list` shows what is already up. Pull someone else’s bot into local with `python scripts/hub.py download other-bot`.

## Data your agent can analyze

Everything below is legal for the agent at decision time (via `PlayerView`, `on_game_end`, and `coup.agent_api`). Full field lists are in [`API.md`](API.md). Do not open `results/` or other agents’ source from the bot.

| Source | What you get |
| --- | --- |
| Your hand | `view.your_cards` (face-down only for you) |
| Public table | Per seat: `coins`, `influence`, `revealed` cards, `name` |
| Public history | `view.history` — actions, blocks, challenges (`success` = bluff caught), proves, losses, eliminations, coin moves. No hidden hands |
| Deck counts | `deck_count`, `copies_per_card`, `total_cards` (infer what’s left with your hand + revealed) |
| Legal moves | `legal_actions` / `legal_responses` for the current phase |
| This game’s result | `on_game_end(view, result)` — placements, points, winner, turns, capped |
| Your memory | Notes on `self` during a game **and across games** in a tournament (object is reused). A timeout kills the process and wipes `self` |
| Opponent identity | In a **tournament**, `PublicPlayer.name` is an opaque UID (`u_…`), stable for the whole run across games and rounds — track play style without learning real submission names. Casual `play.py` still uses agent folder names. A new run mints new UIDs |
| Live standings | `query_standings(TABLE\|ROUND\|TOURNAMENT)` and `query_previous_round_winners()` — points/wins so far, keyed by the same UIDs. `None` outside a tournament (e.g. `play.py`, the checker) |

You are never told who is who by submission name in a scored run. Infer strategies from history and UID-linked memory; standings are public placement stats only.

## Read next

- [`CANDIDATE_GUIDE.md`](CANDIDATE_GUIDE.md) — what “good” looks like and how scoring works
- [`RULES.md`](RULES.md) — rulebook (`tests/test_engine.py` enforces it)
- [`API.md`](API.md) — every type and method your agent may use
- [`ORGANIZER_GUIDE.md`](ORGANIZER_GUIDE.md) — running a tournament / hub
- [`agents/local/README.md`](agents/local/README.md) — local agents short reference

## What is in the repo

| Path | What it is |
| --- | --- |
| `coup/agent_api.py` | The only `coup` module your agent may import |
| `coup/engine/` | Rules and hidden game state. Do not import this |
| `agents/template/agent.py` | Legal starter. Copy it |
| `agents/examples/` | `random`, `honest`, `guard`, `turtle`, `greedy` (plus `bluffer`, `challenger`) |
| `agents/local/` | Scratch agents (gitignored) |
| `agents/submissions/` | Scored agent on disk (gitignored). Upload via hub |
| `.env.example` | Template for the coup-master `.env` |
| `scripts/test_agent.py` | Ready check before you submit |
| `scripts/hub.py` | Upload / list / download via coup-master |
| `start.sh` / `start.ps1` | Create venv, install deps, run dashboard |
| `scripts/serve_dashboard.py` | Local dashboard |
| `scripts/tournament.py` | A round and a leaderboard |
| `scripts/play.py` | One printed game |
| `scripts/replay.py` | Print a saved game |
| `results/` | Round logs. Not committed |
