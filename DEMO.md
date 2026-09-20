# Demo and presentation

Everything here is measured. The numbers come from `evaluation/results/benchmark.md`
(14 scenarios, 5 strategies, 60s budget, 4 repeats) and from CI runs on this
repository. Nothing in this file is a projection.

## The claim, stated honestly

Nemotron reads a diff and works out which tests it is likely to break,
*including tests in files a filename rule would never reach*. It does not win
every comparison, and the sections below say exactly where it loses.

## The one change that shows it

`demo_project/app/coupon.py` truncates a percentage to whole cents:

```python
return (subtotal * percent) // 100
```

Switching that to `round(...)` breaks two tests:

| Test | How it breaks |
|---|---|
| `test_coupon.py::test_percent_discount_truncates_partial_cent` | Directly. Any strategy finds this. |
| `test_checkout.py::test_percent_coupon_changes_total` | **Indirectly.** `checkout.py` is untouched; it just consumes the discounted total. |

The second one is the demo. A filename rule maps `coupon.py` to `test_coupon.py`
and never considers the checkout test. From the per-scenario table, on this
exact change:

- `file_rule` finds **1 of 2** faults
- `nemotron` finds **2 of 2**

## Running it

Two forms. The terminal version is the reliable one; CI is the credible one.

```bash
# Naive baseline: filename correspondence only
./.venv/bin/python main.py run --budget 60 --strategy file_rule

# Nemotron: reads the diff, reaches the checkout test
./.venv/bin/python main.py run --budget 60 --strategy nemotron
```

The line to point at in the output is `selected because:`. That is the model's
own reason for choosing a test, and it is the visible evidence that this is
semantic reasoning rather than string matching on a filename.

In CI, the same thing runs automatically on every pull request and writes to
the job summary. `.github/workflows/testbudget.yml`, dispatchable manually with
a chosen budget and strategy.

## The evidence slide

Do not put the headline recall number on screen by itself. It is true and it
loses the room:

| Strategy | Recall |
|---|---|
| `keyword` | 81% |
| `file_rule` | 77% |
| `nemotron` | 65% |
| `duration` / `history` | 35% |

Put this up instead, which is the same data split by whether a filename rule
could have found the fault at all:

| Faults | `file_rule` | `keyword` | **`nemotron`** |
|---|---|---|---|
| **Not reachable by filename** (36) | 33% | 44% | **64%** |
| Reachable by filename (68) | 100% | 100% | 66% |

The honest sentence to say out loud:

> It is worse at the easy half and roughly twice as good at the hard half. The
> hard half is the half a rule cannot do.

## What to admit before you are asked

Judges reward this and the brief asks for it.

1. **Nemotron loses on overall recall.** A keyword heuristic beats it, 81% to
   65%, because the model sometimes skips the obvious directly-named test in
   favour of a subtle indirect one.
2. **The model answers about half the time.** Measured at 50 of 105 calls.
   Ranking is capped at a slice of the budget, and median latency sits right at
   that cap. When it does not answer, the run silently falls back to a
   deterministic strategy and still goes green.
3. **The obvious next step is a hybrid**, not more prompting: take the direct
   filename matches first, then Nemotron's ordering for everything else. On
   these numbers that is roughly 88%, better than any single strategy measured.
4. **A green selective run does not certify the suite.** That is why
   `full-suite.yml` exists and is the merge gate.

## Timing

| Beat | Time | On screen |
|---|---|---|
| The problem: 139s suite, a four-character change | 30s | The diff |
| Naive filename rule finds 1 of 2 | 60s | `--strategy file_rule` |
| Nemotron finds 2 of 2, and says why | 90s | `--strategy nemotron`, the `selected because:` line |
| Does it actually help? | 60s | The split table above |
| Green here is not green overall | 20s | The two workflows |

## Before you present

- [ ] Open the demo PR early so CI has finished and you have a permanent link.
- [ ] Rehearse until you have a run where Nemotron actually answered. At the
      default cap that may take two or three tries.
- [ ] Consider raising `TESTBUDGET_AI_MAX_SECONDS` (repository variable, or the
      `ai_max_seconds` dispatch input). At a 60s budget, spending 20s on
      ranking still leaves 40s of tests, and the demo stops being a coin flip.
      Say the number out loud if you change it.
- [ ] Have the terminal version ready as a fallback so you are never waiting on
      a CI queue. It needs `NVIDIA_API_KEY` in a local `.env`.
