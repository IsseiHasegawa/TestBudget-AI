# TestBudget AI

A CI assistant that has NVIDIA Nemotron read a pull request diff, work out which
tests the change is likely to break, and run those first inside a fixed time
budget.

> A green selective run does not mean a green suite. The full suite still runs
> on its own path.

## Status

Phases 2 and 3 were swapped during development. The scheduler and the non-AI
ranking came first so that a working selective CI existed before any model was
involved, which also produced the baselines the evaluation compares against.

| Phase | Scope | State |
|---|---|---|
| P1 | Sample app, 30 pytest tests, nodeid collection, duration history, selective execution, JSON report | Done |
| P3 | Git diff analysis, non-AI ranking, budget scheduler, timeouts, extended reporting | Done |
| P2 | Nemotron client, structured output, validation pipeline | Done |
| P4 | GitHub Actions, secrets and permissions | Done |
| P5 | Non-AI baselines, ten or more change scenarios, evaluation | Not started |
| P6 | Demo PR, results view, presentation | Not started |

## Setup

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

The only dependency is pytest. The Nemotron client uses the standard library,
so nothing extra is needed to run it.

## Usage

```bash
# Collect: every real nodeid, its summary and its measured duration
./.venv/bin/python main.py collect

# Analyse a change: which files moved, and which functions and classes inside them
./.venv/bin/python main.py changes                    # uncommitted changes
./.venv/bin/python main.py changes --base origin/main # what a PR would see

# Plan: decide what fits the budget without running anything
./.venv/bin/python main.py select --budget 3

# Run: analyse, rank, pick what fits, execute
./.venv/bin/python main.py run --budget 3

# Compare against a baseline
./.venv/bin/python main.py run --budget 3 --strategy file_rule

# Rank with Nemotron (needs NVIDIA_API_KEY in .env)
./.venv/bin/python main.py select --budget 60 --strategy nemotron

# Run an explicit set of nodeids and save the result as JSON
./.venv/bin/python main.py run \
  --nodeid 'demo_project/tests/test_coupon.py::test_percent_discount_truncates_partial_cent' \
  --nodeid 'demo_project/tests/test_checkout.py::test_percent_coupon_changes_total'

# Full suite, which is also how the duration history gets updated
./.venv/bin/python main.py run --all

# Measured durations, slowest first
./.venv/bin/python main.py history
```

`run` always writes a report to `artifacts/run-<timestamp>.json`, or to
`--json PATH`. The report names the tests that were **not** executed, and why,
alongside the ones that were.

## Layout

```
.github/workflows/
  testbudget.yml        selective CI on a pull request, advisory
  full-suite.yml        the merge gate: every test, no budget, no ranking
src/
  config.py             shared paths, defaults, pytest subprocess environment
  models.py             TestCandidate / TestResult / RunOutcome
  pytest_tb_plugin.py   pytest plugin that exports collection and result data
  test_collector.py     nodeid collection and validation
  change_analyzer.py    changed files and enclosing symbols, from git diff
  nemotron_client.py    the model call: budget-linked timeout, error classification
  model_response.py     response validation, with no network dependency
  prioritizer.py        non-AI ranking (three baselines plus a fallback)
  scheduler.py          budget-constrained selection, deterministic
  test_runner.py        runs given nodeids under a deadline and per-test timeout
  history.py            measured durations and failure counts
  reporter.py           JSON report and console output
demo_project/
  app/                  store logic (cart / coupon / checkout / payment / profile)
  tests/                30 pytest tests
tests_internal/         tests for the tooling itself
data/duration_history.json  measured durations
main.py                 CLI
```

## Ranking strategies

| Strategy | Role | What it does |
|---|---|---|
| `file_rule` | Evaluation baseline | Only test files whose name matches a changed source file |
| `duration` | Evaluation baseline | Ignores the change, runs the quickest tests first |
| `history` | Evaluation baseline | Recently failed tests first |
| `keyword` | Production fallback | The above, plus changed symbol names appearing in a test name or docstring |
| `nemotron` | The real thing | Sends the diff and the candidates to Nemotron for a semantic order, and degrades to `keyword` on any failure |

`file_rule` is kept deliberately simple. Dressing up a baseline until it
quietly encodes the same insight as the model would make the comparison
meaningless. `keyword` is not held back the same way, because its job is to
keep CI useful when no model is available rather than to lose a fair fight.

## Measured: changing the rounding in coupon.py

Switching `_round_percent` from truncation to round-half-up, run with a one
second budget against a 4.6 second suite.

| Strategy | Selected | Failures found | Indirect checkout failure |
|---|---|---|---|
| `file_rule` | 23 / 30 | 1 | **missed** |
| `keyword` | 22 / 30 | 2 | found |

Same budget, one fewer test selected, twice as many failures found.
`file_rule` cannot reach that failure at all: `test_checkout.py` does not carry
the name `coupon.py`.

### Ranking comparison

Where each strategy places the two failing tests. Lower is better, because it
means reaching the failure sooner.

| Strategy | Direct failure (coupon) | Indirect failure (checkout) | Tests to reach both |
|---|---|---|---|
| `file_rule` | 7 | 27 | 27 |
| `duration` | 26 | 27 | 27 |
| `history` | 26 | 27 | 27 |
| `keyword` | 3 | 8 | 8 |
| `nemotron` | 4 | **2** | **4** |

Nemotron is the only strategy that puts the indirect failure near the top. The
reason it returned was "Order total directly computes from coupon discount
which changed rounding method", which states the coupon to checkout dependency
in words.

That row is one successful call. Two of three attempts at the same budget hit
the nine second allowance and degraded to the keyword ordering. The report
records that rate rather than hiding it.

## Continuous integration

Two workflows, and the difference between them matters.

| Workflow | Trigger | What it proves |
|---|---|---|
| `testbudget.yml` | pull request | The selected tests passed inside the budget. Advisory |
| `full-suite.yml` | pull request, push to main, nightly | Every test passed. This is the gate |

**Make `full-suite` the required status check, not `TestBudget`.** A selective
run is fast feedback. It cannot certify a suite it did not finish, and its job
summary says so on every run.

Both workflows take `contents: read` and nothing more. Results go to the job
summary, which needs no permission at all, rather than to a pull request
comment, which would need `pull-requests: write`.

### Untrusted pull requests

Neither workflow uses `pull_request_target`, which would run fork code with
secrets in scope. On `pull_request`, GitHub already withholds secrets from
forks, so a fork PR finds no API key, and the client degrades to the keyword
ranking on its own.

The selective workflow checks the fork flag anyway and forces `keyword` before
the key is ever placed in the environment. That is a second lock on the same
door: the failure being guarded against is a funded API call driven by code
nobody has reviewed.

`tests_internal/test_workflows.py` asserts these properties, because a typo in
YAML would otherwise surface only once it was running against a real pull
request.

### Configuration

| Name | Kind | Purpose |
|---|---|---|
| `NVIDIA_API_KEY` | secret | Omit it and CI still works, ranking with `keyword` |
| `NEMOTRON_MODEL` | variable | Overrides the default model id |
| `NEMOTRON_BASE_URL` | variable | Points at a self-hosted NIM instead of the hosted catalogue |

The selective job runs with `--no-history`, so it never needs to write back to
the repository for the sake of a disposable timing number.

## Design decisions

**Nodeids come from pytest itself.** Rebuilding them from junit-xml class names
breaks on parametrised tests and tests inside classes.
`src/pytest_tb_plugin.py` writes `report.nodeid` verbatim, so every id the
scheduler hands back to pytest is guaranteed to match a collected one.

**Model output never reaches a shell.** Nodeids travel as separate argv
entries, never concatenated into a string. Ids that were not collected are
dropped by `validate_nodeids` before execution.

**The model returns indices, not test ids.** Asking for positions in the
candidate list cuts the response from roughly a thousand tokens to two hundred,
which is the only lever that reliably moves latency. It also makes an invented
test id structurally impossible: an index is either in range or it is not.

**Thinking mode is off.** Measured at 33s against 1.4s without it, on rankings
that did not differ.

**Every rejection case in the validator was observed, not imagined.** Setting
`response_format` to `json_object` still produced malformed JSON from a
generation loop that ran into the token ceiling, and still returned
`ranked_tests` as bare strings instead of objects. The shape is checked rather
than assumed, and an unrecognised shape is rejected rather than repaired.

**Auth failures and rate limits are never retried.** Retrying them only burns
budget. They are reported by name, so a run that quietly lost its model cannot
pass for an assisted one.

**Durations are estimated with a median.** One slow run should not drag the
estimate. An estimate is a prediction rather than a guarantee, so the scheduler
keeps headroom on top of it.

**The budget is enforced at two levels.** The plugin holds a wall-clock
deadline and refuses to start a test past it, and that deadline also bounds
each individual test. Refusing to start a test does nothing about one already
running. The subprocess timeout sits a few seconds later as a backstop and
normally never fires.

**Results are appended one at a time.** A budget-driven run gets stopped
mid-flight as a matter of course. Buffering until session end threw away the
results of tests that had already finished.

**A known false positive in the keyword matcher is left in place.** The word
"round" in the changed `_round_percent` matches "round trip" in a profile test
docstring, which lifts an unrelated avatar upload test. That is a real limit of
token overlap, so it is pinned in `tests_internal/test_ranking.py` rather than
tuned away. Whether the model avoids that mistake is the substance of the
comparison.

**Some demo tests sleep on purpose.** `simulate_io()` in
`demo_project/tests/support.py` stands in for a payment gateway or an image
upload. It is simulated latency, not measured work. The demo app is pure
arithmetic and would finish in microseconds, which leaves a time budget nothing
to schedule around.

**The demo suite is deliberately longer than the budget.** At roughly two and a
half minutes against a 60s budget, something always has to be left out, which
is the only condition under which a ranking can be judged. An earlier version
ran in 4.6s, and every strategy scored identically because every strategy fit
everything. The durations are tuned so the coupon group plus the affected
checkout tests just fit, and the slow unrelated tests cannot.

Set `TB_LATENCY_SCALE=0.02` to shrink every wait while iterating locally.
Durations recorded at a reduced scale describe nothing real, so pass
`--no-history` whenever the scale is not 1.0.

**checkout depends on coupon indirectly.** Changing the rounding in
`coupon.py` breaks the total assertions in `test_checkout.py`. A test filter
based on file names misses exactly this kind of change, and it is the case the
evaluation is built around.

## Verifying

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt

# Everything, at real durations. Takes about two and a half minutes.
./.venv/bin/python -m pytest -q

# The same tests with the simulated waits shrunk, for an edit loop.
TB_LATENCY_SCALE=0.01 ./.venv/bin/python -m pytest -q

# Just the tooling tests, which never wait on anything.
./.venv/bin/python -m pytest tests_internal -q
```

The workflow tests need PyYAML, which is in the dev requirements only. Without
it they skip rather than fail.
