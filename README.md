# Coup sandbox

This is the agent sandbox for the Issa Compass intern hackathon on **Friday 6 November, 1pm, at Cloud 11**. You write a Python program that plays [Coup](https://boardgamegeek.com/boardgame/131357/coup). The engine, the rules, and the opponents are already here. You only edit your agent.

## Five-minute start

You need Python 3.11 or newer.

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/test_agent.py agents/template/agent.py
python scripts/play.py --seed 1
```

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/test_agent.py agents/template/agent.py
python scripts/play.py --seed 1
```

`READY` means your agent plays legal moves. It does not mean it plays well.

## Make your agent

Windows:

```powershell
mkdir agents\submissions\your-name
copy agents\template\agent.py agents\submissions\your-name\agent.py
python scripts/test_agent.py agents/submissions/your-name/agent.py
```

macOS:

```bash
mkdir -p agents/submissions/your-name
cp agents/template/agent.py agents/submissions/your-name/agent.py
python scripts/test_agent.py agents/submissions/your-name/agent.py
```

Use lowercase letters, digits, and hyphens in `your-name`. That folder name is what the leaderboard shows. Edit only that `agent.py`. If you use Cursor or Claude, paste [`AI_PROMPT.md`](AI_PROMPT.md) and tell it your folder name.

Push a branch named `agent/your-name` and open a pull request. The checker runs on that pull request.

## Local agents — get started and see results

Scratch bots for your machine and the dashboard **Local** list. Not scored submissions (those stay under `agents/submissions/`). Folders are auto-discovered; no catalog edit. More detail: [`agents/local/README.md`](agents/local/README.md).

### Checklist

1. Finish **Five-minute start** above so `test_agent.py` prints `READY` on the template.
2. Skim [`RULES.md`](RULES.md) once; keep [`API.md`](API.md) open while you edit.
3. Create a local agent, get `READY`, play one game, then open the dashboard (steps below).
4. Edit `agent.py`, re-run the tester, play again. Restart the dashboard if it was already running so the **Local** list refreshes.
5. Optional: paste [`AI_PROMPT.md`](AI_PROMPT.md) into Cursor or Claude and name your folder. The model writes the code; the agent itself must not call an LLM at play time.

### Create and check

macOS / Linux:

```bash
mkdir -p agents/local/your-name
cp agents/template/agent.py agents/local/your-name/agent.py
python scripts/test_agent.py agents/local/your-name/agent.py
```

Windows:

```powershell
mkdir agents\local\your-name
copy agents\template\agent.py agents\local\your-name\agent.py
python scripts/test_agent.py agents/local\your-name\agent.py
```

Use lowercase letters, digits, and hyphens in `your-name`. Edit only that `agent.py`.

### See results

One printed game (add `--reveal` to show hidden cards after the game):

```bash
python scripts/play.py --agents your-name,honest,bluffer,challenger --seed 1
```

A short local tournament (writes under `results/`):

```bash
python scripts/tournament.py --agents your-name random honest bluffer --games-per-agent 4 --no-sandbox --run-id local-demo --force
```

Dashboard (scoreboard + playback):

```bash
python scripts/serve_dashboard.py --port 8765
```

Open `http://127.0.0.1:8765`. **Play Games** → **Local** → add your agent (or **Add all**), run a session, then open **Games** → **Watch**. Or open an existing run under `results/` (for example `local-demo`). Playback speed and **Reveal cards** are on the watch view.

### Update a local agent

Change `agents/local/your-name/agent.py`, then:

```bash
python scripts/test_agent.py agents/local/your-name/agent.py
python scripts/play.py --agents your-name,honest --seed 1
```

Same folder name keeps the same id in `--agents` and the dashboard. New folder = new agent. Restart `serve_dashboard.py` after adding a folder so `/api/agents` picks it up.

## Read next

- [`CANDIDATE_GUIDE.md`](CANDIDATE_GUIDE.md) tells you what to build and how you are scored.
- [`RULES.md`](RULES.md) is the rulebook. The tests in `tests/test_engine.py` enforce it.
- [`API.md`](API.md) is every type and method you can use.
- [`ORGANIZER_GUIDE.md`](ORGANIZER_GUIDE.md) is for the people running the event.
- [`agents/local/README.md`](agents/local/README.md) is the short local-agents reference.

## What is in the repo

| Path | What it is |
| --- | --- |
| `coup/agent_api.py` | The only `coup` module your agent may import |
| `coup/engine/` | Rules and the hidden game state. Do not import this |
| `agents/template/agent.py` | A legal agent with comments. Copy it |
| `agents/examples/` | `random`, `honest`, `bluffer`, and `challenger` |
| `agents/local/` | Scratch agents for local play (gitignored). Auto-listed from the directory |
| `scripts/test_agent.py` | The "am I allowed to submit" check |
| `scripts/play.py` | One game, printed |
| `scripts/tournament.py` | A round and a leaderboard |
| `scripts/replay.py` | Print a saved game |
| `results/` | Round logs. Not committed |

`python scripts/play.py --agents template,random,honest,bluffer --seed 1` is a good way to watch a strategy.

Internal Issa Compass hiring exercise. Do not distribute this repo.
