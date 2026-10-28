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

## Read next

- [`CANDIDATE_GUIDE.md`](CANDIDATE_GUIDE.md) tells you what to build and how you are scored.
- [`RULES.md`](RULES.md) is the rulebook. The tests in `tests/test_engine.py` enforce it.
- [`API.md`](API.md) is every type and method you can use.
- [`ORGANIZER_GUIDE.md`](ORGANIZER_GUIDE.md) is for the people running the event.

## What is in the repo

| Path | What it is |
| --- | --- |
| `coup/agent_api.py` | The only `coup` module your agent may import |
| `coup/engine/` | Rules and the hidden game state. Do not import this |
| `agents/template/agent.py` | A legal agent with comments. Copy it |
| `agents/examples/` | `random`, `honest`, `bluffer`, and `challenger` |
| `scripts/test_agent.py` | The "am I allowed to submit" check |
| `scripts/play.py` | One game, printed |
| `scripts/tournament.py` | A round and a leaderboard |
| `scripts/replay.py` | Print a saved game |
| `results/` | Round logs. Not committed |

`python scripts/play.py --agents template,random,honest,bluffer --seed 1` is a good way to watch a strategy.

Internal Issa Compass hiring exercise. Do not distribute this repo.
