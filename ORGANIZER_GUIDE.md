# Organizer guide

For people running a Coup agent tournament with this sandbox. Players should not need this.

This repo is the shared sandbox. Player bots stay gitignored on their machines and are submitted through **coup-master** using a `.env` you distribute (URL + API key).

## Before players start

From a fresh clone, with no extra explanation, someone new should be able to:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/test_agent.py agents/template/agent.py
python scripts/play.py --seed 1
```

Or `./start.sh` / `.\start.ps1` for the dashboard. `test_agent.py` must print `READY`. If a step is confusing, fix the docs in this repo.

Prepare one `.env` per player (same values for everyone is fine):

```text
COUP_MASTER_URL=https://coup-master.example.com
COUP_MASTER_API_KEY=…
```

Keep the API key out of the public repo, chat logs, and screenshots. Ship placeholders only in `.env.example`.

Then run a staff dry run:

```powershell
python scripts/tournament.py --round 1 --games-per-agent 6 --no-sandbox --run-id staff-dry-run --seed 1
```

Open `results/staff-dry-run/round_1/leaderboard.html` in a browser. That is the projector page. `--no-sandbox` is for rehearsal only. It is faster and it does not kill a slow agent. Scored rounds use the default: a separate process per agent and a hard 1 second limit.

Freeze the rules before players clone:

```powershell
git tag v1
git push origin v1
```

Do that only after the dry run, on the commit you want them to use. Do not move the tag once people have started.

## During a tournament

Each player clones the tagged repo, builds `agents/submissions/<name>/agent.py` (gitignored), puts your `.env` in the repo root, gets `READY`, and uploads:

```powershell
python scripts/hub.py upload <name> --full-name "Ada Lovelace"
```

At each checkpoint:

```powershell
python scripts/collect_submissions.py --force
python scripts/tournament.py --round 1 --submissions --games-per-agent 20 --run-id tournament --seed 1
```

`collect_submissions.py` downloads approved hub agents into `agents/submissions/` (also gitignored on the organizer machine). Use `--force` to refresh from the hub before a scored round.

Use `--round 2`, `--round 3`, and so on for later checkpoints. Do not reuse a round number unless you pass `--force`, which deletes that round's files. Cumulative standings are written to `results/tournament/standings.html` from every `round_*` folder under that run id.

`--submissions` refuses to start if fewer than two agents have been collected. Add the examples with `--with-examples` only for a demo, not for the scored round.

A round is reproducible from `--seed` for seating, but each deck is shuffled with a secret held in the tournament process. Agents do not receive that secret. Logs written at the end of a game include that game's deck seed so you can debug a finished game. They do not let a later game be predicted.

Each tournament run mints opaque public UIDs (`results/<run-id>/player_uids.json`) and seats those at the table the agents see. Leaderboards and game logs still use real agent names; agents only ever get the UIDs (stable across games and rounds in that run).

## Reading results

- `results/<run-id>/round_N/leaderboard.html` is the page to put on a screen.
- `results/<run-id>/standings.html` adds every round in that run.
- `results/<run-id>/round_N/games/g0001.jsonl` is one game. `python scripts/replay.py <that file>` prints it.
- Illegal moves, errors, and timeouts are columns. A strong win rate with a large error count is a broken agent that got lucky defaults, not a finished one.

For the live projector dashboard (scoreboard + game playback with speed and reveal):

```powershell
python scripts/serve_dashboard.py --results results --port 8765
```

Open `http://127.0.0.1:8765`. **New session** lets you pick agents, add multiple rounds, and play them in the background. Finished games appear under Games while the session is still running — Watch any completed table without waiting for the round to finish. Or pick an existing run, switch Standings / Round tabs, open Games, then Watch. Playback supports 2s / 1s / 0.5s / 0.25s per event. **Reveal cards** shows face-down hands from the log.

Each event line in a new game log includes a `state` object: public coins / influence / revealed cards, plus `hand` (face-down cards) for the reveal toggle. Older logs without `state` still open; reveal stays disabled.

Archive the `results/<run-id>` folder when you are done. It is gitignored on purpose.

## If something breaks

- Hub upload fails static check or `NOT READY`: the player fixes locally and re-uploads. You can still collect whatever is already on the hub; the tournament will play defaults for bad decisions and count them. Drop them only if the file does not import at all.
- `collect_submissions.py` needs `COUP_MASTER_URL` (from `.env`). It does not need the API key to download approved agents. Reject a bad name with `python scripts/hub.py reject <name>`.
- The sandbox is one process per agent for the whole round. A timeout kills that process and starts it again on the next decision. One bad agent cannot hang the table.
- Staff rehearsal uses `--no-sandbox`. The scored command does not. An agent that cheats by reading engine memory will pass a local `--no-sandbox` game and fail, or play randomly, in the real round.

## Commands worth remembering

```powershell
python scripts/play.py --agents template,random,honest --seed 3 --reveal
python scripts/replay.py results/tournament/round_1/games/g0001.jsonl
python scripts/collect_submissions.py --force
python scripts/tournament.py --round 1 --agents honest,bluffer,challenger,random --games-per-agent 4 --no-sandbox --run-id demo --force
python scripts/serve_dashboard.py --port 8765
```

`--reveal` prints hidden cards. Use it when a log line is confusing. Do not run the scored round with it. It only affects the local printout, not the log, but it is the wrong habit at the table.
