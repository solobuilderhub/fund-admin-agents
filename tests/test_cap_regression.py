"""
The incentive cap, which is the reason this repo exists.

A waterfall that pays the tiers alone hands the Investment Manager $1,408,809.71
on a $30M exit. The agreement caps that at 20% of cumulative realized gains net
of realized losses and unrealized depreciation, which is $700,000.00. The
$708,809.71 difference is withheld.

If someone removes the cap, or lets unrealized appreciation into net gains, this
test fails by exactly that amount. That is the point.
"""

from __future__ import annotations

from decimal import Decimal

CAP = Decimal("700000.00")
UNCAPPED = Decimal("1408809.71")
WITHHELD = Decimal("708809.71")


def test_cap_is_twenty_percent_of_net_gains(manifest):
    """Net gains exclude unrealized appreciation. 20% of $3.5M, not $12.5M."""
    cap = manifest("waterfall")["cap"]

    net_gains = Decimal(cap["net_gains"])
    assert net_gains == Decimal("3500000.00")

    # realized gains less realized losses less unrealized depreciation
    assert net_gains == (
        Decimal(cap["realized_gains"])
        - Decimal(cap["realized_losses"])
        - Decimal(cap["unrealized_depreciation"])
    )

    assert Decimal(cap["cap"]) == CAP


def test_tier_calculation_pays_more_than_the_cap(manifest):
    """Without the cap the manager is paid $1,408,809.71."""
    cap = manifest("waterfall")["cap"]

    assert Decimal(cap["im_before_cap"]) == UNCAPPED
    assert UNCAPPED > CAP


def test_withheld_is_the_difference(manifest):
    """$708,809.71 is withheld, and the identity holds to the cent."""
    cap = manifest("waterfall")["cap"]

    assert Decimal(cap["withheld"]) == WITHHELD
    assert UNCAPPED - CAP == WITHHELD


def test_unrealized_appreciation_is_ignored(manifest):
    """The $9M of unrealized appreciation must not reach net gains.

    If it did, the cap would be $2.5M and nothing would be withheld at all.
    This is the failure a generic waterfall model produces.
    """
    cap = manifest("waterfall")["cap"]

    appreciation = Decimal(cap["unrealized_appreciation_ignored"])
    assert appreciation == Decimal("9000000.00")

    # what a model that counted appreciation would have allowed
    generous = Decimal("0.20") * (Decimal(cap["net_gains"]) + appreciation)
    assert generous > UNCAPPED  # i.e. the cap would never bite

    # and what it did allow
    assert CAP < UNCAPPED


def test_proceeds_still_balance_after_the_cap(manifest):
    """Withholding must not invent or lose money: members + manager + withheld."""
    doc = manifest("waterfall")
    totals = doc["totals"]

    total = Decimal(doc["disposition"]) + Decimal(doc["current"])
    members = Decimal(totals["member_total"])
    im_paid = Decimal(totals["im_disposition_paid"])
    im_current = Decimal(totals["im_current"])
    withheld = Decimal(totals["im_withheld"])

    assert withheld == WITHHELD
    assert members + im_paid + im_current + withheld == total
