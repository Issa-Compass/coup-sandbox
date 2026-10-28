"""Runners, the sandbox, scheduling, and the submission checker."""

from __future__ import annotations

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
    assert placement_points(1, 6) == 5
