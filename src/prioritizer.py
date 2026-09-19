"""Non-AI test ranking.

Two distinct jobs live here and must not be conflated:

* The named baselines (`file_rule`, `duration`, `history`) are the comparison
  arms the evaluation measures the model against. They stay deliberately
  simple, because dressing up a baseline until it quietly encodes the same
  insight as the model would make the comparison meaningless.
* `keyword` is the fallback the scheduler uses when the model is unavailable.
  It is allowed to be the best non-AI ranking we can write, since here the goal
  is to keep CI useful rather than to lose a fair fight.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from src.change_analyzer import ChangeSet
from src.models import FAILING_OUTCOMES, TestCandidate

FILE_RULE = "file_rule"
DURATION = "duration"
HISTORY = "history"
KEYWORD = "keyword"

STRATEGIES = (FILE_RULE, DURATION, HISTORY, KEYWORD)

# Tokens this short, or this generic, match everything and rank nothing.
MIN_TOKEN_LENGTH = 4
STOP_TOKENS = frozenset(
    {"test", "tests", "self", "none", "true", "false", "from", "with", "this", "that", "demo", "project"}
)

CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
NON_WORD = re.compile(r"[^0-9a-zA-Z]+")

# Duration assumed for a test that has never been measured. Pessimistic on
# purpose: an unknown test should not crowd out a measured one.
UNKNOWN_DURATION_S = 1.0


@dataclass
class RankedTest:
    nodeid: str
    score: float
    reason: str
    strategy: str

    def to_dict(self) -> dict:
        return asdict(self)


def _tokens(text: str) -> set[str]:
    expanded = CAMEL_BOUNDARY.sub(" ", text)
    parts = NON_WORD.sub(" ", expanded).lower().split()
    return {part for part in parts if len(part) >= MIN_TOKEN_LENGTH and part not in STOP_TOKENS}


def _candidate_tokens(candidate: TestCandidate) -> set[str]:
    return _tokens(f"{candidate.nodeid} {candidate.name} {candidate.summary}")


def _duration(candidate: TestCandidate) -> float:
    if candidate.estimated_duration_s is None:
        return UNKNOWN_DURATION_S
    return candidate.estimated_duration_s


def _sorted(ranked: list[RankedTest], candidates: list[TestCandidate]) -> list[RankedTest]:
    """Highest score first, then cheapest, then nodeid.

    The duration tiebreak matters: among equally relevant tests, running the
    quick one first fits more of them inside the same budget.
    """
    durations = {candidate.nodeid: _duration(candidate) for candidate in candidates}
    return sorted(ranked, key=lambda item: (-item.score, durations[item.nodeid], item.nodeid))


def rank_by_file_rule(candidates: list[TestCandidate], changes: ChangeSet) -> list[RankedTest]:
    """Baseline: a test file whose name matches a changed source file.

    This is the rule most teams reach for first, and the one that structurally
    cannot see that changing coupon.py moves the totals asserted in
    test_checkout.py.
    """
    changed_stems = {Path(changed.path).stem for changed in changes.files if changed.is_python}

    ranked = []
    for candidate in candidates:
        test_stem = Path(candidate.file).stem
        bare = test_stem[5:] if test_stem.startswith("test_") else test_stem
        if bare and bare in changed_stems:
            ranked.append(
                RankedTest(candidate.nodeid, 1.0, f"test file matches changed {bare}.py", FILE_RULE)
            )
        else:
            ranked.append(RankedTest(candidate.nodeid, 0.0, "no matching changed file", FILE_RULE))
    return _sorted(ranked, candidates)


def rank_by_duration(candidates: list[TestCandidate], changes: ChangeSet) -> list[RankedTest]:
    """Baseline: ignore the change entirely and run the quickest tests first."""
    ranked = [
        RankedTest(candidate.nodeid, 0.0, f"estimated {_duration(candidate):.3f}s", DURATION)
        for candidate in candidates
    ]
    return _sorted(ranked, candidates)


def rank_by_history(candidates: list[TestCandidate], changes: ChangeSet) -> list[RankedTest]:
    """Baseline: tests that failed recently, then tests that never ran."""
    ranked = []
    for candidate in candidates:
        if candidate.last_outcome in FAILING_OUTCOMES:
            score, reason = 2.0, f"last run {candidate.last_outcome}"
        elif candidate.fail_count:
            score, reason = 1.0, f"{candidate.fail_count} past failure(s)"
        elif candidate.run_count == 0:
            score, reason = 0.5, "never run"
        else:
            score, reason = 0.0, "no failure history"
        ranked.append(RankedTest(candidate.nodeid, score, reason, HISTORY))
    return _sorted(ranked, candidates)


def rank_by_keyword(candidates: list[TestCandidate], changes: ChangeSet) -> list[RankedTest]:
    """Fallback: file correspondence, plus changed symbol names seen in a test."""
    changed_stems = {Path(changed.path).stem for changed in changes.files if changed.is_python}
    changed_dirs = {str(Path(changed.path).parent) for changed in changes.files}
    symbol_tokens = _tokens(" ".join(changes.all_symbols()))
    stem_tokens = _tokens(" ".join(changed_stems))

    ranked = []
    for candidate in candidates:
        test_stem = Path(candidate.file).stem
        bare = test_stem[5:] if test_stem.startswith("test_") else test_stem
        tokens = _candidate_tokens(candidate)

        score = 0.0
        notes = []

        if bare and bare in changed_stems:
            score += 4.0
            notes.append(f"matches changed {bare}.py")

        shared_symbols = sorted(tokens & symbol_tokens)
        if shared_symbols:
            # One shared token is a weak signal. A docstring saying "round trip"
            # collides with a change to _round_percent and means nothing by it,
            # so a single hit is worth far less than several.
            score += min(2.0, 0.5 * len(shared_symbols))
            notes.append(f"mentions changed symbol(s): {', '.join(shared_symbols[:3])}")

        shared_stems = sorted((tokens & stem_tokens) - set(shared_symbols))
        if shared_stems:
            score += min(1.5, 0.75 * len(shared_stems))
            notes.append(f"mentions changed module(s): {', '.join(shared_stems[:3])}")

        top_level = str(Path(candidate.file).parts[0]) if candidate.file else ""
        if top_level and any(directory.startswith(top_level) for directory in changed_dirs):
            score += 0.25
            notes.append("same package as a changed file")

        if candidate.last_outcome in FAILING_OUTCOMES:
            score += 0.5
            notes.append(f"last run {candidate.last_outcome}")

        ranked.append(
            RankedTest(candidate.nodeid, score, "; ".join(notes) or "no signal", KEYWORD)
        )
    return _sorted(ranked, candidates)


_DISPATCH = {
    FILE_RULE: rank_by_file_rule,
    DURATION: rank_by_duration,
    HISTORY: rank_by_history,
    KEYWORD: rank_by_keyword,
}


def rank(strategy: str, candidates: list[TestCandidate], changes: ChangeSet) -> list[RankedTest]:
    if strategy not in _DISPATCH:
        raise ValueError(f"unknown strategy {strategy!r}; expected one of {sorted(_DISPATCH)}")
    return _DISPATCH[strategy](candidates, changes)
