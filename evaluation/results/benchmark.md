# Evaluation, 60s budget

Recall and missed faults are exact. Time to first failure is estimated from measured durations rather than observed, since selection is deterministic and re-executing adds nothing to it.

## Per strategy

| Strategy | Faults found | Recall | Scenarios fully caught | Scenarios missed entirely | Mean tests run | Mean time to first failure |
|---|---|---|---|---|---|---|
| `keyword` | 84 / 104 | **81%** | 44 / 48 | 0 / 48 | 15.3 | 8.7s |
| `file_rule` | 80 / 104 | 77% | 40 / 48 | 0 / 48 | 16.4 | 10.9s |
| `nemotron` | 68 / 104 | 65% | 29 / 48 | 8 / 48 | 12.8 | 18.0s |
| `duration` | 36 / 104 | 35% | 24 / 48 | 12 / 48 | 19.0 | 17.4s |
| `history` | 36 / 104 | 35% | 24 / 48 | 12 / 48 | 19.0 | 17.4s |

## Recall, split by what a filename rule can reach

| Faults | `keyword` | `file_rule` | `nemotron` | `duration` | `history` |
|---|---|---|---|---|---|
| Faults a filename rule cannot reach | 16/36 (44%) | 12/36 (33%) | 23/36 (64%) | 4/36 (11%) | 4/36 (11%) |
| Faults in the test file named after the change | 68/68 (100%) | 68/68 (100%) | 45/68 (66%) | 32/68 (47%) | 32/68 (47%) |

## Model reliability

- `nemotron`: 50 of 105 calls answered (48%); 6 scenario(s) fell back; mean 4.68s spent ranking per scenario

CI gets one allowance and falls back. The retries above exist to characterise the ranking, not to describe production behaviour.

## Per scenario

| Scenario | Shape | Faults | `keyword` | `file_rule` | `nemotron` | `duration` | `history` |
|---|---|---|---|---|---|---|---|
| `coupon_rounding` | direct and indirect | 2 | 2/2 | 1/2 miss | 2/2 | 0/2 miss | 0/2 miss |
| `coupon_cap_off_by_one` | direct | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `coupon_floor_at_zero_removed` | direct | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `shipping_threshold` | direct | 3 | 3/3 | 3/3 | 1/3 miss | 1/3 miss | 1/3 miss |
| `tax_rate` | direct, several tests | 6 | 6/6 | 6/6 | 5/6 miss | 1/6 miss | 1/6 miss |
| `card_flat_fee` | indirect | 7 | 2/7 miss | 2/7 miss | 3/7 miss | 1/7 miss | 1/7 miss |
| `wallet_fee_rate` | direct, misleading name overlap | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `luhn_accepts_anything` | direct | 1 | 1/1 | 1/1 | 1/1 | 0/1 miss | 0/1 miss |
| `email_tld_length` | direct, unrelated module | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `display_name_limit` | direct, unrelated module | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `avatar_size_limit` | direct, slowest test | 1 | 1/1 | 1/1 | 0/1 miss | 0/1 miss | 0/1 miss |
| `cart_stops_merging_lines` | direct, several tests | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `benign_docstring` | benign | 0 | 16 run | 19 run | 11 run | 19 run | 19 run |
| `benign_constant_rename` | benign | 0 | 16 run | 16 run | 15 run | 19 run | 19 run |
