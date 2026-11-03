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

Use lowercase letters, digits, underscore, and hyphen in `your-name`. That folder name is what the hub and leaderboard show. Edit only that `agent.py`. The `agents/submissions/` folder is **gitignored** — do not commit your bot or open a PR with it.

At the event, organizers hand you a `.env` (coup-master URL + API key). Copy it to the repo root (or fill [`.env.example`](.env.example)), get `READY`, then:

```bash
python scripts/hub.py upload your-name --full-name "Ada Lovelace"
```

If you use Cursor or Claude, paste [`AI_PROMPT.md`](AI_PROMPT.md) and tell it your folder name.

## Local agents — get started and see results

Scratch bots for your machine and the dashboard **Local** list. Also gitignored. Scored hand-in is still hub upload from `agents/submissions/`. Folders are auto-discovered; no catalog edit. More detail: [`agents/local/README.md`](agents/local/README.md).

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

## Shared hub (coup-master)

Submission is hub upload, not a GitHub PR. Put the organizers’ `.env` in the repo root (`COUP_MASTER_URL` + `COUP_MASTER_API_KEY`). `scripts/hub.py` and the dashboard load it automatically.

```bash
# after READY on agents/submissions/your-name/agent.py
python scripts/hub.py list
python scripts/hub.py upload your-name --full-name "Ada Lovelace"
python scripts/hub.py download other-bot   # into agents/local/
```

Uploads that pass the static safety check are listed immediately. A real **full name** (at least two names; middle names OK) is required. Organizers can remove a bad submission with `python scripts/hub.py reject your-name`.

Names: `A–Z a–z 0–9 _ -` only, and must not already exist on the hub. Master rejects unsafe imports the same way `test_agent.py` does (it never runs your code). The dashboard also exposes `/api/hub/*` when `.env` or `--master-url` is set.

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
| `agents/local/` | Scratch agents (gitignored). Auto-listed from the directory |
| `agents/submissions/` | Your scored agent (gitignored). Upload via hub |
| `.env.example` | Template for the in-person coup-master `.env` |
| `scripts/test_agent.py` | The "am I allowed to submit" check |
| `scripts/hub.py` | Upload / list / download via coup-master |
| `scripts/collect_submissions.py` | Organizer: pull hub agents onto disk for a round |
| `scripts/play.py` | One game, printed |
| `scripts/tournament.py` | A round and a leaderboard |
| `scripts/replay.py` | Print a saved game |
| `results/` | Round logs. Not committed |

`python scripts/play.py --agents template,random,honest,bluffer --seed 1` is a good way to watch a strategy.
