# Local agents

Scratch agents for local play and the dashboard. Not scored submissions.
Candidate work still goes in `agents/submissions/`.

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
python scripts/tournament.py --agents your-name random honest --games-per-agent 4 --no-sandbox --run-id local-demo --force
python scripts/serve_dashboard.py --port 8765
```

In the dashboard, open **Play Games** → **Local** → add the agent (or **Add all**).

## Shared hub

Pull someone else’s safe submission into this folder (needs `COUP_MASTER_URL`):

```bash
python scripts/hub.py download their-name
# writes agents/local/their-name/agent.py
```

Upload yours with a unique name (`A–Z a–z 0–9 _ -`):

```bash
python scripts/hub.py upload your-name
```
