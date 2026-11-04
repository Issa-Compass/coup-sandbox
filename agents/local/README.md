# Local agents

Scratch agents for local play and the dashboard. Not scored submissions.
Scored work goes in `agents/submissions/` (also gitignored) and is submitted
with `scripts/hub.py` after you have a coup-master `.env`.

Agent folders under this directory are gitignored. The dashboard and
`--agents <name>` discover whatever is on disk: each `*/agent.py` is one agent.

## Layout

```text
agents/local/<name>/agent.py
```

`<name>` is lowercase letters, digits, and hyphens only. That folder name is the
agent id: the dashboard **Local** list and `--agents <name>` both use it.

Discovery is automatic. Put `agent.py` in a new folder under `agents/local/` —
no catalog edit, no dashboard edit. Restart `serve_dashboard.py` if it was
already running so `/api/agents` refreshes.

## Add a new local agent

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
python scripts/test_agent.py agents\local\your-name\agent.py
```

Edit only that `agent.py`. One `Agent` subclass per file. Import only
`coup.agent_api` (and the standard library).

## Run it

```bash
python scripts/play.py --agents your-name,honest --seed 1
python scripts/tournament.py --round 1 --agents your-name random honest --games-per-agent 4 --no-sandbox --run-id local-demo --force
python scripts/serve_dashboard.py --port 8765
```

In the dashboard, open **Play Games** → **Local** → add the agent (or **Add all**).

## Shared hub

Put a coup-master `.env` in the repo root first.

Pull someone else’s safe submission into this folder:

```bash
python scripts/hub.py download their-name
# writes agents/local/their-name/agent.py
```

Scored upload is from `agents/submissions/<name>/` (needs the API key in `.env`):

```bash
python scripts/hub.py upload your-name --full-name "Ada Lovelace"
```
