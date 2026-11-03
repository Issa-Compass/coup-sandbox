# Coup sandbox

This is the agent sandbox for the Issa Compass intern hackathon on **Friday 6 November, 1pm, at Cloud 11**. You write a Python program that plays [Coup](https://boardgamegeek.com/boardgame/131357/coup). The engine, the rules, and the opponents are already here. You only edit your agent.

You need Python 3.11 or newer. Work through the path below in order.

## 1. Setup

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

`READY` means the template plays legal moves. It does not mean it plays well. Keep the venv activated for every command below.

## 2. Dashboard

```bash
python scripts/serve_dashboard.py --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Leave this running in a terminal. After you add or rename an agent folder, restart the server so **Local** refreshes.

## 3. Baseline tournament (example bots)

Smoke-test the shipped ladder (`random`, `honest`, `bluffer`, `challenger`) with no custom code:

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
python scripts/play.py --agents your-name,honest,bluffer,challenger --seed 1
python scripts/tournament.py --agents your-name random honest bluffer challenger --games-per-agent 4 --no-sandbox --run-id local-demo --force
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

2. At the event, organizers hand you a `.env` (coup-master URL + API key). Put it in the repo root (or fill [`.env.example`](.env.example)).

3. Upload:

```bash
python scripts/hub.py upload your-name --full-name "Ada Lovelace"
```

A real full name (at least two names) is required. Names: `A–Z a–z 0–9 _ -` only. Re-upload replaces your hub entry. `scripts/hub.py list` shows what is already up. Pull someone else’s bot into local with `python scripts/hub.py download other-bot`.

## Read next

- [`CANDIDATE_GUIDE.md`](CANDIDATE_GUIDE.md) — what “good” looks like and how scoring works
- [`RULES.md`](RULES.md) — rulebook (`tests/test_engine.py` enforces it)
- [`API.md`](API.md) — every type and method your agent may use
- [`ORGANIZER_GUIDE.md`](ORGANIZER_GUIDE.md) — staff running the event
- [`agents/local/README.md`](agents/local/README.md) — local agents short reference

## What is in the repo

| Path | What it is |
| --- | --- |
| `coup/agent_api.py` | The only `coup` module your agent may import |
| `coup/engine/` | Rules and hidden game state. Do not import this |
| `agents/template/agent.py` | Legal starter. Copy it |
| `agents/examples/` | `random`, `honest`, `bluffer`, `challenger` |
| `agents/local/` | Scratch agents (gitignored) |
| `agents/submissions/` | Scored agent on disk (gitignored). Upload via hub |
| `.env.example` | Template for the in-person coup-master `.env` |
| `scripts/test_agent.py` | Ready check before you submit |
| `scripts/hub.py` | Upload / list / download via coup-master |
| `scripts/serve_dashboard.py` | Local dashboard |
| `scripts/tournament.py` | A round and a leaderboard |
| `scripts/play.py` | One printed game |
| `scripts/replay.py` | Print a saved game |
| `results/` | Round logs. Not committed |
