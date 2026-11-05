# Findings

Three findings that changed how I think about this problem. Each one is a case where a competent-looking calculation produces a defensible number that is wrong.

## 1. The incentive cap is not a percentage of profit

The waterfall has four tiers: return of capital, 6% preferred return compounded annually, a 10% catch-up, then a 90/10 split. On a $30M exit with $1.2M of current income, the tiers pay the Investment Manager **$1,408,809.71**.

The agreement then caps incentive on Disposition Proceeds at **20% of cumulative realized gains net of realized losses and unrealized depreciation**. Unrealized *appreciation* does not count.

```
realized gains          14,000,000.00
realized losses         -3,500,000.00
unrealized depreciation -7,000,000.00
                        --------------
net gains                3,500,000.00
20% cap                    700,000.00

incentive before cap     1,408,809.71
withheld                   708,809.71
```

The portfolio holds $9,000,000 of unrealized appreciation. Count it, and net gains become $12.5M, the cap becomes $2.5M, and nothing is withheld at all. Every dollar of that $708,809.71 depends on one definition.

The agreement does not say where withheld amounts go. It says the excess is not paid. The run reports it as withheld pending confirmation rather than distributing it to members, because redistributing money the agreement does not allocate to anyone is a different decision.

`tests/test_cap_regression.py` fails by exactly $708,809.71 if the cap is removed.

## 2. One allocation key is never enough

Drawdown 7 needs $10.92M: $9.0M of portfolio investment, $1.5M of management fees, $420k of expenses. The agreement allocates each purpose on a different basis.

| Purpose | Basis | Clause |
|---|---|---|
| Portfolio Investment | Remaining Capital Commitment % | s.5.1(a) |
| Management Fees | Invested Capital % | s.5.1(a) |
| Fund Expenses | Capital Commitment % | s.5.1(a) |

A single commitment-percentage split looks right, produces plausible numbers, and is wrong for every member. The error concentrates on the member who defaulted on Drawdown 5: it would call **$385,505.83** more than it owes, from an investor that has already failed to fund once.

There is a second-order trap. A member admitted at a subsequent closing owes an equalisation payment. If the equalisation is treated as unfunded commitment, that member's remaining-commitment percentage is overstated and they are loaded with too much of the investment.

## 3. Ten business days is not fourteen calendar days

The manager instructs a due date of 9 October. The agreement requires ten business days' notice. Fourteen calendar days suggests nine October is comfortably inside the window.

It is six business days. Columbus Day falls on 12 October 2026 and the Federal Reserve is closed, so it does not count as a business day even though the NYSE would otherwise trade. The earliest compliant date is **16 October, not 15 October**.

A one-day error in a capital call notice is not a rounding issue. It is a notice that can be challenged, and in the worst case a call that has to be reissued and re-cured.

`references/business_days_2026.json` records both holiday calendars separately and intersects them. The definition requires both exchanges open, not either.
