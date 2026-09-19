# Evaluation, 60s budget

Recall and missed faults are exact. Time to first failure is estimated from measured durations rather than observed, since selection is deterministic and re-executing adds nothing to it.

## Per strategy

| Strategy | Faults found | Recall | Scenarios fully caught | Scenarios missed entirely | Mean tests run | Mean time to first failure |
|---|---|---|---|---|---|---|
| `keyword` | 21 / 26 | **81%** | 11 / 12 | 0 / 12 | 15.3 | 8.7s |
| `file_rule` | 20 / 26 | 77% | 10 / 12 | 0 / 12 | 16.4 | 10.9s |
| `nemotron` | 16 / 26 | 62% | 8 / 12 | 2 / 12 | 12.5 | 19.1s |
| `duration` | 9 / 26 | 35% | 6 / 12 | 3 / 12 | 19.0 | 17.4s |
| `history` | 9 / 26 | 35% | 6 / 12 | 3 / 12 | 19.0 | 17.4s |

## Model reliability

- `nemotron`: 11 of 24 calls answered (46%); 3 scenario(s) fell back; mean 5.61s spent ranking per scenario

CI gets one allowance and falls back. The retries above exist to characterise the ranking, not to describe production behaviour.

## Per scenario

| Scenario | Shape | Faults | `keyword` | `file_rule` | `nemotron` | `duration` | `history` |
|---|---|---|---|---|---|---|---|
| `coupon_rounding` | direct and indirect | 2 | 2/2 | 1/2 miss | 2/2 | 0/2 miss | 0/2 miss |
| `coupon_cap_off_by_one` | direct | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `coupon_floor_at_zero_removed` | direct | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `shipping_threshold` | direct | 3 | 3/3 | 3/3 | 3/3 | 1/3 miss | 1/3 miss |
| `tax_rate` | direct, several tests | 6 | 6/6 | 6/6 | 3/6 miss | 1/6 miss | 1/6 miss |
| `card_flat_fee` | indirect | 7 | 2/7 miss | 2/7 miss | 2/7 miss | 1/7 miss | 1/7 miss |
| `wallet_fee_rate` | direct, misleading name overlap | 1 | 1/1 | 1/1 | 0/1 miss | 1/1 | 1/1 |
| `luhn_accepts_anything` | direct | 1 | 1/1 | 1/1 | 1/1 | 0/1 miss | 0/1 miss |
| `email_tld_length` | direct, unrelated module | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `display_name_limit` | direct, unrelated module | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `avatar_size_limit` | direct, slowest test | 1 | 1/1 | 1/1 | 0/1 miss | 0/1 miss | 0/1 miss |
| `cart_stops_merging_lines` | direct, several tests | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `benign_docstring` | benign | 0 | 16 run | 19 run | 14 run | 19 run | 19 run |
| `benign_constant_rename` | benign | 0 | 16 run | 16 run | 14 run | 19 run | 19 run |
