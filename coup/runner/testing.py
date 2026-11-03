"""Check that a candidate agent is legal to submit."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from coup.runner.catalog import EXAMPLES, resolve_agent
from coup.runner.load_agent import agent_name_from_path, load_agent_class
from coup.runner.match import play_game
from coup.runner.players import InProcessPlayer, SandboxPlayer, open_player
from coup.runner.static_check import validate_source

BUCKETS = ("random", "honest", "bluffer", "challenger", "mixed")
TABLE_SIZES = (3, 4, 5, 6)


@dataclass
class BucketScore:
    name: str
    games: int = 0
    wins: int = 0


@dataclass
class Report:
    path: Path
    ready: bool
    issues: list[str] = field(default_factory=list)
    illegal: int = 0
    errors: int = 0
    timeouts: int = 0
    decisions: int = 0
    decision_time: float = 0.0
    buckets: list[BucketScore] = field(default_factory=list)

    def text(self) -> str:
        lines = [f"Agent file: {self.path}"]
        if self.issues:
            lines.append("Problems:")
            lines.extend(f"  - {issue}" for issue in self.issues)
        lines.append(
            f"games checked: {sum(bucket.games for bucket in self.buckets)}  "
            f"illegal: {self.illegal}  errors: {self.errors}  timeouts: {self.timeouts}"
        )
        if self.decisions:
            lines.append(f"average decision: {1000 * self.decision_time / self.decisions:.3f} ms")
        for bucket in self.buckets:
            rate = 0 if not bucket.games else 100 * bucket.wins / bucket.games
            lines.append(f"win rate vs {bucket.name}: {rate:.0f}% ({bucket.wins}/{bucket.games})")
        lines.append("READY" if self.ready else "NOT READY")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "ready": self.ready,
            "issues": list(self.issues),
            "illegal": self.illegal,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "decisions": self.decisions,
            "decision_time": self.decision_time,
            "games": sum(bucket.games for bucket in self.buckets),
            "buckets": [
                {"name": bucket.name, "games": bucket.games, "wins": bucket.wins}
                for bucket in self.buckets
            ],
            "text": self.text(),
        }


def evaluate(path: Path, games: int = 200, timeout: float = 1.0, sandbox_games: int = 3) -> Report:
    report = Report(path=path, ready=False)
    source = path.read_text(encoding="utf-8")
    report.issues.extend(validate_source(source))
    if report.issues:
        return report
    try:
        agent_cls = load_agent_class(path)
        agent_cls()
    except Exception as exc:
        report.issues.append(f"import failed: {type(exc).__name__}: {exc}")
        return report
    name = agent_name_from_path(path)
    candidate = open_player(path, name, sandbox=False, timeout=timeout)
    per_bucket, remainder = divmod(games, len(BUCKETS))
    for index, bucket_name in enumerate(BUCKETS):
        count = per_bucket + (1 if index < remainder else 0)
        score = BucketScore(bucket_name)
        for game_index in range(count):
            won, played = _play_bucket_game(
                candidate, name, bucket_name, game_index, timeout, index
            )
            score.games += 1
            score.wins += int(won)
            report.illegal += int(played.penalties[name]["illegal"])
            report.errors += int(played.penalties[name]["errors"])
            report.timeouts += int(played.penalties[name]["timeouts"])
            report.decisions += int(played.penalties[name]["decisions"])
            report.decision_time += float(played.penalties[name]["decision_time"])
        report.buckets.append(score)
    if sandbox_games:
        sandbox = SandboxPlayer(path, name, timeout)
        try:
            for game_index in range(sandbox_games):
                issue = _sandbox_game(sandbox, name, game_index, timeout)
                if issue:
                    report.issues.append(issue)
                    break
        finally:
            sandbox.close()
    report.ready = not report.issues and report.illegal == 0 and report.errors == 0 and report.timeouts == 0
    return report


def _play_bucket_game(candidate, name: str, bucket: str, game_index: int, timeout: float, bucket_index: int):
    size = TABLE_SIZES[game_index % len(TABLE_SIZES)]
    opponents = _opponents(bucket, size - 1, game_index)
    seated: list = []
    used = {name}
    for offset, opponent in enumerate(opponents):
        label = f"{opponent}_{offset}"
        while label in used:
            offset += 1
            label = f"{opponent}_{offset}"
        used.add(label)
        seated.append(open_player(resolve_agent(opponent), label, sandbox=False, timeout=timeout))
    seat = game_index % size
    players = seated[:seat] + [candidate] + seated[seat:]
    played = play_game(players, seed=10_000 * bucket_index + game_index + 1)
    won = played.result.place_of(players.index(candidate)) == 1
    return won, played


def _opponents(bucket: str, count: int, game_index: int) -> list[str]:
    if bucket == "mixed":
        order = ["random", "honest", "bluffer", "challenger"]
        return [order[(game_index + index) % len(order)] for index in range(count)]
    return [bucket] * count


def _sandbox_game(candidate: SandboxPlayer, name: str, game_index: int, timeout: float) -> str | None:
    others = [
        InProcessPlayer(load_agent_class(EXAMPLES[alias])(), f"{alias}_{offset}", timeout)
        for offset, alias in enumerate(("random", "honest"))
    ]
    players = [candidate, *others]
    if game_index % 2:
        players = [others[0], candidate, others[1]]
    try:
        played = play_game(players, seed=50_000 + game_index, max_turns=30)
    except Exception as exc:
        return f"sandbox game failed: {type(exc).__name__}: {exc}"
    penalties = played.penalties[name]
    if penalties["illegal"] or penalties["errors"] or penalties["timeouts"]:
        detail = candidate.load_error or "sandbox penalties"
        return (
            f"sandbox game was not clean "
            f"(illegal={penalties['illegal']}, errors={penalties['errors']}, "
            f"timeouts={penalties['timeouts']}): {detail}"
        )
    return None

