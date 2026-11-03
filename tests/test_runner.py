"""Runners, the sandbox, scheduling, and the submission checker."""

from __future__ import annotations

import json
import time
from pathlib import Path

from coup.agent_api import Agent, Action, ActionType
from coup.engine.rules import placement_points
from coup.runner.catalog import EXAMPLES, safe_branch_name
from coup.runner.load_agent import load_agent_class
from coup.runner.match import play_game
from coup.runner.players import SandboxPlayer, open_player
from coup.runner.schedule import build_tables, choose_sizes
from coup.runner.static_check import static_issues
from coup.runner.testing import evaluate
from scripts.ci_submissions import submission_dirs


def test_choose_sizes_prefers_four_to_six():
    assert choose_sizes(6) == [6]
    assert choose_sizes(2) == [2]
    assert sorted(choose_sizes(7)) == [3, 4]
    assert sorted(choose_sizes(12)) == [6, 6]
    assert sorted(choose_sizes(10)) == [5, 5]
    for count in range(2, 18):
        sizes = choose_sizes(count)
        assert sum(sizes) == count
        assert all(2 <= size <= 6 for size in sizes)
        assert 1 not in sizes


def test_every_agent_plays_the_same_number_of_games():
    names = [f"p{i}" for i in range(7)]
    tables = build_tables(names, games_per_agent=4, seed=3, prefer=5)
    counts = {name: 0 for name in names}
    for table in tables:
        assert len(table) == len(set(table))
        assert 2 <= len(table) <= 6
        for name in table:
            counts[name] += 1
    assert set(counts.values()) == {4}


def test_build_tables_is_deterministic():
    names = [f"p{i}" for i in range(7)]
    first = build_tables(names, games_per_agent=12, seed=11, prefer=5)
    second = build_tables(names, games_per_agent=12, seed=11, prefer=5)
    assert first == second
    assert first != build_tables(names, games_per_agent=12, seed=12, prefer=5)


def test_pair_meetings_stay_balanced_across_tables():
    """Multi-table fields should share opponents evenly, not shuffle-luck piles."""

    from collections import Counter
    from itertools import combinations

    names = [f"p{i}" for i in range(7)]
    games = 42
    tables = build_tables(names, games_per_agent=games, seed=7, prefer=5)
    pair_counts: Counter[tuple[str, str]] = Counter()
    for table in tables:
        assert 2 <= len(table) <= 6
        for left, right in combinations(table, 2):
            key = (left, right) if left < right else (right, left)
            pair_counts[key] += 1

    # Every unordered pair should meet at least once over a long round.
    expected_pairs = {tuple(sorted(pair)) for pair in combinations(names, 2)}
    assert set(pair_counts) == expected_pairs

    values = list(pair_counts.values())
    assert max(values) - min(values) <= 2
    # Rough expectation for 7 agents on 4+3 is ~3/7 of games together.
    mean = sum(values) / len(values)
    assert 0.35 * games <= mean <= 0.55 * games


def test_example_bots_finish_and_replay():
    def run(seed: int) -> list[str]:
        players = [
            open_player(EXAMPLES[alias], alias, sandbox=False, timeout=1)
            for alias in ("random", "honest", "bluffer", "challenger")
        ]
        played = play_game(players, seed=seed, max_turns=50)
        assert played.game.card_counts()
        assert all(item["errors"] == 0 and item["illegal"] == 0 for item in played.penalties.values())
        return [event.message for event in played.game.history]

    assert run(7) == run(7)
    assert run(7) != run(8)


def test_game_log_includes_board_state_and_hands(tmp_path: Path):
    from coup.runner.reporting import write_game_log

    players = [
        open_player(EXAMPLES[alias], alias, sandbox=False, timeout=1)
        for alias in ("random", "honest")
    ]
    played = play_game(players, seed=3, max_turns=20)
    path = tmp_path / "g0001.jsonl"
    write_game_log(path, played, seed=3, game_id="g0001")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [row for row in rows if row["type"] == "event"]
    assert events
    assert len(played.game.board_snapshots) == len(played.game.history)
    for row in events:
        state = row["state"]
        assert "phase" in state
        for player in state["players"]:
            assert "coins" in player
            assert "hand" in player
            assert len(player["hand"]) == player["influence"]
            assert len(player["revealed"]) + player["influence"] <= 2


def test_illegal_action_and_exception_do_not_stop_the_game():
    class Bad(Agent):
        def choose_action(self, view):
            return Action(ActionType.INCOME, target=0)

    class Boom(Agent):
        def choose_action(self, view):
            raise RuntimeError("nope")

    from coup.runner.players import InProcessPlayer

    bad = InProcessPlayer(Bad(), "bad", 1)
    boom = InProcessPlayer(Boom(), "boom", 1)
    other = open_player(EXAMPLES["template"], "template", sandbox=False, timeout=1)
    played = play_game([bad, boom, other], seed=1, max_turns=4)
    assert played.game.finished
    assert played.penalties["bad"]["illegal"] >= 1
    assert played.penalties["boom"]["errors"] >= 1


def test_static_check_bans_network_and_engine_imports():
    assert static_issues("from coup.agent_api import Agent\n") == []
    banned = static_issues("import socket\nfrom coup.engine import Game\n")
    assert any("socket" in issue for issue in banned)
    assert any("coup.engine" in issue for issue in banned)
    assert static_issues("from coup import engine\n")
    assert static_issues("x = __import__('socket')\n")
    assert any("eval" in i for i in static_issues("y = eval('1')\nfrom coup.agent_api import Agent\n"))
    assert any("pickle" in i for i in static_issues("import pickle\nfrom coup.agent_api import Agent\n"))
    for mod in ("os", "sys", "pathlib", "importlib"):
        assert any(mod in i for i in static_issues(f"import {mod}\nfrom coup.agent_api import Agent\n")), mod
    assert any("getattr" in i for i in static_issues("x = getattr(object, 'x')\n"))
    assert any("open" in i for i in static_issues("f = open('x')\n"))
    assert any("__class__" in i for i in static_issues("x = (1).__class__\n"))


def test_validate_source_requires_one_agent_subclass():
    from coup.runner.static_check import validate_source

    good = (
        "from coup.agent_api import Agent, Action, default_action, PlayerView\n\n"
        "class Bot(Agent):\n"
        "    def choose_action(self, view: PlayerView) -> Action:\n"
        "        return default_action(view)\n"
    )
    assert validate_source(good) == []
    assert any("exactly one" in i for i in validate_source("from coup.agent_api import Agent\n"))
    twin = good + "\nclass Other(Agent):\n    pass\n"
    assert any("exactly one" in i for i in validate_source(twin))
    assert any("os" in i for i in static_issues("import os\nfrom coup.agent_api import Agent\n"))
    assert any("getattr" in i for i in static_issues("getattr(object, 'x')\n"))
    assert any("__class__" in i for i in static_issues("x = (1).__class__\n"))


def test_load_finds_only_the_subclass_defined_in_the_file():
    cls = load_agent_class(EXAMPLES["challenger"])
    assert cls.__name__ == "ChallengerBot"


def test_branch_names_and_ci_path_filter():
    assert safe_branch_name("origin/agent/ada-lovelace") == "ada-lovelace"
    assert safe_branch_name("origin/main") is None
    assert safe_branch_name("agent/ada") == "ada"
    assert submission_dirs(["README.md", "coup/engine/game.py"]) == []
    assert submission_dirs(["agents/submissions/missing/agent.py"]) == []


def test_template_evaluate_is_ready():
    report = evaluate(EXAMPLES["template"], games=5, timeout=1, sandbox_games=1)
    assert report.ready, report.text()
    assert report.illegal == 0 and report.errors == 0 and report.timeouts == 0


def test_sandbox_kills_a_hung_agent():
    code = (
        "import time\n"
        "from coup.agent_api import Agent, default_action\n"
        "class Sleeper(Agent):\n"
        "    def choose_action(self, view):\n"
        "        time.sleep(5)\n"
        "        return default_action(view)\n"
    )
    path = Path("tests") / "_sleeper_agent.py"
    path.write_text(code, encoding="utf-8")
    try:
        sleeper = SandboxPlayer(path, "sleeper", timeout=0.4)
        other = open_player(EXAMPLES["template"], "template", sandbox=False, timeout=1)
        started = time.perf_counter()
        played = play_game([sleeper, other], seed=1, max_turns=1)
        elapsed = time.perf_counter() - started
        assert elapsed < 4
        assert played.penalties["sleeper"]["timeouts"] >= 1
        assert played.game.finished
    finally:
        path.unlink(missing_ok=True)
        sleeper.close()


def test_sandbox_refuses_engine_import(tmp_path: Path):
    path = tmp_path / "cheat.py"
    path.write_text(
        "import coup.engine\nfrom coup.agent_api import Agent\nclass Cheat(Agent):\n    pass\n",
        encoding="utf-8",
    )
    player = SandboxPlayer(path, "cheat", timeout=1)
    try:
        from coup.engine.game import Game

        game = Game(["cheat", "other"], seed=1)
        player.on_game_start(game.view_for(0), 123)
        assert player.errors >= 1
        assert player.load_error
    finally:
        player.close()


def test_points_constant_is_shared():
    assert placement_points(1, 6) == 6


def test_list_available_agents_includes_examples():
    from coup.runner.catalog import list_available_agents

    agents = list_available_agents()
    ids = [row["id"] for row in agents]
    assert ids[:4] == ["random", "honest", "bluffer", "challenger"]
    assert "template" not in ids
    for row in agents:
        if row["kind"] == "local":
            assert row["path"].startswith("agents/local/")
            assert row["id"] == row["name"]
            assert row["path"].endswith("/agent.py")


def test_local_agents_indexes_directory(tmp_path: Path, monkeypatch):
    import coup.runner.catalog as catalog

    bot = tmp_path / "scratch" / "agent.py"
    bot.parent.mkdir()
    bot.write_text("# test local agent\n")
    monkeypatch.setattr(catalog, "LOCAL", tmp_path)

    assert catalog.local_agents() == [bot]
    assert catalog.resolve_agent("scratch") == bot


def test_list_available_agents_includes_indexed_local(tmp_path: Path, monkeypatch):
    import coup.runner.catalog as catalog

    local_root = tmp_path / "local"
    bot = local_root / "scratch" / "agent.py"
    bot.parent.mkdir(parents=True)
    bot.write_text("# test local agent\n")
    monkeypatch.setattr(catalog, "LOCAL", local_root)
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    monkeypatch.setattr(catalog, "EXAMPLES", {})
    monkeypatch.setattr(catalog, "SUBMISSIONS", tmp_path / "submissions")

    assert catalog.list_available_agents() == [
        {
            "id": "scratch",
            "name": "scratch",
            "kind": "local",
            "path": "local/scratch/agent.py",
        }
    ]


def test_local_and_arena_same_name_are_distinct(tmp_path: Path, monkeypatch):
    import coup.runner.catalog as catalog

    local_root = tmp_path / "local"
    sub_root = tmp_path / "submissions"
    local_bot = local_root / "milo" / "agent.py"
    arena_bot = sub_root / "milo" / "agent.py"
    local_bot.parent.mkdir(parents=True)
    arena_bot.parent.mkdir(parents=True)
    local_bot.write_text("# local\n")
    arena_bot.write_text("# arena\n")
    monkeypatch.setattr(catalog, "LOCAL", local_root)
    monkeypatch.setattr(catalog, "SUBMISSIONS", sub_root)
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    monkeypatch.setattr(catalog, "EXAMPLES", {})

    agents = catalog.list_available_agents()
    by_id = {row["id"]: row for row in agents}
    assert by_id["milo"]["kind"] == "local"
    # Disk submissions are a run cache only — not in the dashboard catalog.
    assert "arena:milo" not in by_id
    assert catalog.resolve_agent("milo") == local_bot
    assert catalog.resolve_agent("arena:milo") == arena_bot
    assert catalog.display_name_for_token("arena:milo") == "milo"


def test_unique_instance_names_suffixes_duplicates():
    from coup.runner.load_agent import unique_instance_names

    assert unique_instance_names(["random", "honest"]) == ["random", "honest"]
    assert unique_instance_names(["random", "random", "honest", "random"]) == [
        "random",
        "random_2",
        "honest",
        "random_3",
    ]


def test_run_round_allows_duplicate_agent_paths(tmp_path: Path):
    from coup.runner.tournament import run_round

    events = []
    run_round(
        [EXAMPLES["random"], EXAMPLES["random"], EXAMPLES["honest"]],
        games_per_agent=1,
        master_seed=1,
        round_number=1,
        run_id="dup-instances",
        timeout=1.0,
        sandbox=False,
        table_size=3,
        results_root=tmp_path,
        on_progress=events.append,
    )
    start = next(event for event in events if event["phase"] == "round_start")
    assert start["agents"] == ["random_bot", "random_bot_2", "honest_bot"]


def test_run_round_reports_progress(tmp_path: Path):
    from coup.runner.tournament import run_round

    events = []
    run_round(
        [EXAMPLES["random"], EXAMPLES["honest"]],
        games_per_agent=1,
        master_seed=1,
        round_number=1,
        run_id="progress-demo",
        timeout=1.0,
        sandbox=False,
        table_size=2,
        results_root=tmp_path,
        on_progress=events.append,
    )
    phases = [event["phase"] for event in events]
    assert phases[0] == "round_start"
    assert "game" in phases
    assert phases[-1] == "round_done"
    assert (tmp_path / "progress-demo" / "round_1" / "games" / "g0001.jsonl").is_file()


def test_query_standings_is_none_outside_tournament():
    from coup.agent_api import StandingsScope, query_previous_round_winners, query_standings
    from coup.runner.players import InProcessPlayer

    seen: dict[str, object] = {}

    class Probe(Agent):
        def on_game_start(self, view, seed: int) -> None:
            seen["start"] = query_standings(StandingsScope.ROUND)

        def choose_action(self, view):
            seen["action"] = query_standings(StandingsScope.TABLE)
            seen["winners"] = query_previous_round_winners()
            return super().choose_action(view)

    probe = InProcessPlayer(Probe(), "probe", 1.0)
    other = InProcessPlayer(Agent(), "other", 1.0)
    play_game([probe, other], seed=1, max_turns=2)
    assert seen["start"] is None
    assert seen["action"] is None
    assert seen["winners"] is None


def test_play_game_binds_standings_scopes(tmp_path: Path):
    from coup.agent_api import PreviousRoundWinner, StandingsScope, query_previous_round_winners, query_standings
    from coup.runner.players import InProcessPlayer
    from coup.runner.standings import build_snapshot, empty_stat
    from coup.runner.tournament import run_round
    from coup.serialize import from_data, to_data

    stats = {
        "alpha": {**empty_stat("alpha"), "games": 2, "points": 6, "wins": 2},
        "beta": {**empty_stat("beta"), "games": 2, "points": 2, "wins": 0},
        "gamma": empty_stat("gamma"),
    }
    prior = {"alpha": {**empty_stat("alpha"), "games": 4, "points": 10, "wins": 3}}
    winners = (
        PreviousRoundWinner(round=1, name="alpha", games=4, points=10, wins=3, avg_points=2.5),
    )
    snapshot = build_snapshot(
        run_id="r",
        round_number=2,
        game_index=3,
        game_id="g0003",
        table=["beta", "gamma"],
        round_stats=stats,
        prior_stats=prior,
        previous_round_winners=winners,
    )
    assert snapshot.round_rows[0].name == "alpha"
    assert from_data(to_data(snapshot)).game_id == "g0003"

    table_rows = None
    tourney = None
    prev = None

    class Seer(Agent):
        def on_game_start(self, view, seed: int) -> None:
            nonlocal table_rows, tourney, prev
            table_rows = query_standings(StandingsScope.TABLE)
            tourney = query_standings(StandingsScope.TOURNAMENT)
            prev = query_previous_round_winners()

    seer = InProcessPlayer(Seer(), "seer", 1.0)
    other = InProcessPlayer(Agent(), "other", 1.0)
    play_game([seer, other], seed=2, max_turns=1, standings=snapshot)
    assert table_rows is not None
    assert [row.name for row in table_rows] == ["beta", "gamma"]
    assert table_rows[0].rank == 1
    assert tourney is not None
    assert tourney[0].name == "alpha"
    assert tourney[0].games == 6
    assert prev == winners

    run_round(
        [EXAMPLES["random"], EXAMPLES["honest"]],
        games_per_agent=1,
        master_seed=2,
        round_number=1,
        run_id="standings-smoke",
        timeout=1.0,
        sandbox=False,
        table_size=2,
        results_root=tmp_path,
        force=True,
    )
    assert (tmp_path / "standings-smoke" / "round_1" / "summary.json").is_file()


def test_sandbox_agent_can_query_standings(tmp_path: Path):
    from coup.runner.players import SandboxPlayer, open_player
    from coup.runner.standings import build_snapshot, empty_stat

    agent_file = tmp_path / "standings_bot.py"
    agent_file.write_text(
        """
from coup.agent_api import Agent, StandingsScope, default_action, query_standings

class StandingsBot(Agent):
    def on_game_start(self, view, seed: int) -> None:
        rows = query_standings(StandingsScope.ROUND)
        if rows is None or [row.name for row in rows] != ["alpha", "beta"]:
            raise RuntimeError(f"bad standings: {rows!r}")

    def choose_action(self, view):
        return default_action(view)
""".lstrip(),
        encoding="utf-8",
    )
    snapshot = build_snapshot(
        run_id="s",
        round_number=1,
        game_index=1,
        game_id="g0001",
        table=["alpha", "beta"],
        round_stats={
            "alpha": {**empty_stat("alpha"), "games": 1, "points": 3, "wins": 1},
            "beta": empty_stat("beta"),
        },
        prior_stats={},
        previous_round_winners=(),
    )
    sandboxed = SandboxPlayer(agent_file, "alpha", timeout=2.0)
    other = open_player(EXAMPLES["random"], "beta", sandbox=False, timeout=1.0)
    try:
        played = play_game([sandboxed, other], seed=1, max_turns=3, standings=snapshot)
        assert played.penalties["alpha"]["errors"] == 0
    finally:
        sandboxed.close()
        other.close()


def test_load_prior_rounds_reads_winners(tmp_path: Path):
    from coup.runner.standings import load_prior_rounds

    run = tmp_path / "run"
    round1 = run / "round_1"
    round1.mkdir(parents=True)
    (round1 / "summary.json").write_text(
        json.dumps(
            {
                "round": 1,
                "agents": [
                    {
                        "name": "hero",
                        "games": 2,
                        "points": 4,
                        "wins": 2,
                        "illegal": 0,
                        "errors": 0,
                        "timeouts": 0,
                        "decisions": 10,
                        "decision_time": 0.1,
                    },
                    {
                        "name": "side",
                        "games": 2,
                        "points": 0,
                        "wins": 0,
                        "illegal": 0,
                        "errors": 0,
                        "timeouts": 0,
                        "decisions": 10,
                        "decision_time": 0.1,
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    prior, winners = load_prior_rounds(run, current_round=2)
    assert prior["hero"]["points"] == 4
    assert len(winners) == 1
    assert winners[0].name == "hero"
    assert winners[0].round == 1


def test_assign_uids_are_opaque_and_unique():
    from coup.runner.identity import UID_PREFIX, assign_uids

    mapping = assign_uids(["alpha", "beta", "gamma"])
    assert set(mapping) == {"alpha", "beta", "gamma"}
    assert len(set(mapping.values())) == 3
    assert all(uid.startswith(UID_PREFIX) for uid in mapping.values())
    assert "alpha" not in mapping.values()


def test_tournament_persists_uids_and_writes_real_names_to_logs(tmp_path: Path):
    from coup.runner.identity import UID_PREFIX
    from coup.runner.tournament import run_round

    seen_path = tmp_path / "seen_names.jsonl"
    probe_file = tmp_path / "probe_bot" / "agent.py"
    probe_file.parent.mkdir()
    probe_file.write_text(
        "import json\n"
        "from pathlib import Path\n"
        "from coup.agent_api import Agent, StandingsScope, default_action, query_standings\n"
        f"SEEN = Path({str(seen_path)!r})\n"
        "class ProbeBot(Agent):\n"
        "    def on_game_start(self, view, seed: int) -> None:\n"
        "        rows = query_standings(StandingsScope.ROUND) or ()\n"
        "        SEEN.open('a', encoding='utf-8').write(json.dumps({\n"
        "            'players': [p.name for p in view.players],\n"
        "            'standings': [r.name for r in rows],\n"
        "        }) + '\\n')\n"
        "    def choose_action(self, view):\n"
        "        return default_action(view)\n",
        encoding="utf-8",
    )

    run_round(
        [probe_file, EXAMPLES["random"]],
        games_per_agent=2,
        master_seed=9,
        round_number=1,
        run_id="anon-demo",
        timeout=1.0,
        sandbox=False,
        table_size=2,
        results_root=tmp_path,
        force=True,
    )

    uids_path = tmp_path / "anon-demo" / "player_uids.json"
    assert uids_path.is_file()
    uids = json.loads(uids_path.read_text(encoding="utf-8"))
    assert set(uids) == {"probe_bot", "random_bot"}
    assert all(value.startswith(UID_PREFIX) for value in uids.values())
    assert set(uids.values()).isdisjoint(uids)

    log_path = tmp_path / "anon-demo" / "round_1" / "games" / "g0001.jsonl"
    header = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert set(header["players"]) == {"probe_bot", "random_bot"}
    assert set(header["public_ids"]) == set(uids.values())

    summary = json.loads((tmp_path / "anon-demo" / "round_1" / "summary.json").read_text())
    assert {row["name"] for row in summary["agents"]} == {"probe_bot", "random_bot"}

    seen_lines = [
        json.loads(line) for line in seen_path.read_text(encoding="utf-8").splitlines() if line
    ]
    assert len(seen_lines) >= 2
    for line in seen_lines:
        assert set(line["players"]) == set(uids.values())
        assert "probe_bot" not in line["players"]
        assert "random_bot" not in line["players"]
        assert set(line["standings"]).issubset(set(uids.values()))

    run_round(
        [probe_file, EXAMPLES["random"]],
        games_per_agent=1,
        master_seed=10,
        round_number=2,
        run_id="anon-demo",
        timeout=1.0,
        sandbox=False,
        table_size=2,
        results_root=tmp_path,
        force=True,
    )
    assert json.loads(uids_path.read_text(encoding="utf-8")) == uids


def test_public_ids_hide_real_names_across_games():
    from coup.agent_api import StandingsScope, query_standings
    from coup.runner.players import InProcessPlayer
    from coup.runner.standings import build_snapshot, empty_stat

    class Memo(Agent):
        def __init__(self):
            self.ids: list[str] = []
            self.opponents: list[str] = []
            self.standings_names: list[str] = []

        def on_game_start(self, view, seed: int) -> None:
            self.ids.append(view.players[view.you].name)
            self.opponents.append(next(p.name for p in view.players if p.seat != view.you))
            rows = query_standings(StandingsScope.TABLE)
            if rows:
                self.standings_names.extend(row.name for row in rows)

    memo = Memo()
    alpha_uid, beta_uid = "u_aaaaaa", "u_bbbbbb"
    memo_player = InProcessPlayer(memo, "memo", 1.0)
    memo_player.public_id = alpha_uid
    other = InProcessPlayer(Agent(), "other", 1.0)
    other.public_id = beta_uid
    snapshot = build_snapshot(
        run_id="x",
        round_number=1,
        game_index=1,
        game_id="g0001",
        table=[alpha_uid, beta_uid],
        round_stats={
            alpha_uid: empty_stat(alpha_uid),
            beta_uid: empty_stat(beta_uid),
        },
        prior_stats={},
        previous_round_winners=(),
    )
    play_game([memo_player, other], seed=1, max_turns=2, standings=snapshot)
    play_game([other, memo_player], seed=2, max_turns=2, standings=snapshot)
    assert memo.ids == [alpha_uid, alpha_uid]
    assert set(memo.opponents) == {beta_uid}
    assert "memo" not in memo.ids
    assert "other" not in memo.opponents
    assert set(memo.standings_names) <= {alpha_uid, beta_uid}
