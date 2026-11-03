# Organizer guide

For Kat, Alyza, Nay, and Andy. Candidates should not need this.

The event is **Friday 6 November, 1pm, Cloud 11**. Share this private repo with staff before that. Invite candidates when the build window starts, so everyone learns the rules at the same time. Remote candidates are not in this room. They still do a 1:1 with Andy, and a later round with Aaron or Nay if that goes well.

## Before Friday

From a fresh clone, with no extra explanation, Kat or Alyza should be able to:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/test_agent.py agents/template/agent.py
python scripts/play.py --seed 1
```

`test_agent.py` must print `READY`. If a step is confusing, fix the docs in this repo. Do not explain it in Slack instead. The candidates will not have that Slack thread.

Then run a staff round:

```powershell
python scripts/tournament.py --round 1 --games-per-agent 6 --no-sandbox --run-id staff-dry-run --seed 1
```

Open `results/staff-dry-run/round_1/leaderboard.html` in a browser. That is the projector page. `--no-sandbox` is for this rehearsal only. It is faster and it does not kill a slow agent. The event uses the default, which is a separate process per agent and a hard 1 second limit.

Freeze the rules before candidates arrive:

```powershell
git tag nov6-v1
git push origin nov6-v1
```

Do that only after the dry run, on the commit you want them to clone. Do not move the tag once people have started.

## During the event

Each candidate clones the tagged repo, makes `agents/submissions/<name>/agent.py`, and opens a pull request from `agent/<name>`. GitHub runs `pytest` and then `scripts/test_agent.py` on every submission folder the pull request touches.

At each checkpoint (for example every hour, then a final):

```powershell
python scripts/collect_submissions.py
python scripts/tournament.py --round 1 --submissions --games-per-agent 20 --run-id nov6 --seed 1
```

Use `--round 2`, `--round 3`, and so on for later checkpoints. Do not reuse a round number unless you pass `--force`, which deletes that round's files. Cumulative standings are written to `results/nov6/standings.html` from every `round_*` folder under that run id.

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

Copy the `results/nov6` folder to Drive at the end. It is gitignored on purpose.

## If something breaks

- A pull request is red because `test_agent.py` is `NOT READY`. That agent can still be collected, and the tournament will play defaults for bad decisions and count them. You do not have to drop them unless the file does not import at all.
- `collect_submissions.py` only copies `agents/submissions` from branches named `agent/<name>` on `origin`. A branch with another name is ignored. Run it from a clean checkout so it does not mix with local edits.
- The sandbox is one process per agent for the whole round. A timeout kills that process and starts it again on the next decision. One bad agent cannot hang the table.
- Staff rehearsal uses `--no-sandbox`. The scored command does not. An agent that cheats by reading engine memory will pass a local `--no-sandbox` game and fail, or play randomly, in the real round.

## Commands worth remembering

```powershell
python scripts/play.py --agents template,random,honest --seed 3 --reveal
python scripts/replay.py results/nov6/round_1/games/g0001.jsonl
python scripts/tournament.py --round 1 --agents honest,bluffer,challenger,random --games-per-agent 4 --no-sandbox --run-id demo --force
python scripts/serve_dashboard.py --port 8765
```

`--reveal` prints hidden cards. Use it when a log line is confusing. Do not run the scored round with it. It only affects the local printout, not the log, but it is the wrong habit at the table.
