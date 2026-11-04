# Candidate agents

Work here. Do **not** commit this folder — it is gitignored (only this README is tracked).

```text
agents/submissions/<your-name>/agent.py
```

`<your-name>` is letters, digits, underscore, and hyphen. That name is what the hub and scoreboard show.

1. Copy `agents/template/agent.py` into your folder.
2. Get `READY` from `python scripts/test_agent.py agents/submissions/<your-name>/agent.py`.
3. Put a coup-master `.env` in the repo root (URL + API key; see `.env.example`).
4. Submit with `python scripts/hub.py upload <your-name> --full-name "Your Full Name"`.

Scratch experiments can also live under `agents/local/` (also gitignored). Scored hand-in is hub upload from this folder.
