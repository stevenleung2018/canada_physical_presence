"""Unit tests for the physical presence calculator."""

from datetime import date, timedelta

import pytest

from physical_presence import (
    Absence,
    AbsenceReason,
    ApplicantInput,
    Period,
    PrePRPeriod,
    calculate,
    earliest_eligible_date,
    eligibility_window,
    validate,
)
from physical_presence.calculator import REQUIRED_DAYS, subtract_years

# ---------------------------------------------------------------- date helpers


def test_eligibility_window_is_five_years_before_application():
    window = eligibility_window(date(2026, 10, 19))
    assert window.start == date(2021, 10, 19)
    assert window.end == date(2026, 10, 18)
    assert window.days == 1826  # includes one Feb 29 (2024)


def test_subtract_years_handles_leap_day():
    assert subtract_years(date(2024, 2, 29), 5) == date(2019, 2, 28)


def test_period_rejects_reversed_dates():
    with pytest.raises(ValueError):
        Period(date(2025, 1, 2), date(2025, 1, 1))


@pytest.mark.parametrize(
    ("departure", "return_date", "expected"),
    [
        (date(2025, 1, 1), date(2025, 1, 1), 0),  # same-day trip
        (date(2025, 1, 1), date(2025, 1, 2), 0),  # overnight: both days count in Canada
        (date(2025, 1, 1), date(2025, 1, 10), 8),
    ],
)
def test_absence_days_exclude_departure_and_return(departure, return_date, expected):
    assert Absence(departure, return_date).days_absent == expected


# ------------------------------------------------------------- calculation


def test_full_pr_period_no_absences():
    app = date(2026, 10, 19)
    res = calculate(ApplicantInput(application_date=app, pr_date=date(2020, 1, 1)))
    assert res.pr_credit == res.window.days == 1826
    assert res.eligible


def test_exactly_1095_pr_days_is_eligible():
    app = date(2026, 10, 19)
    pr_date = app - timedelta(days=REQUIRED_DAYS)
    res = calculate(ApplicantInput(application_date=app, pr_date=pr_date))
    assert res.pr_credit == REQUIRED_DAYS
    assert res.eligible
    res_short = calculate(ApplicantInput(application_date=app, pr_date=pr_date + timedelta(days=1)))
    assert not res_short.eligible
    assert res_short.shortfall == 1


def test_absences_reduce_pr_credit():
    data = ApplicantInput(
        application_date=date(2026, 10, 19),
        pr_date=date(2020, 1, 1),
        absences=[Absence(date(2025, 1, 1), date(2025, 1, 11))],  # 9 full days away
    )
    res = calculate(data)
    assert res.pr_days_absent == 9
    assert res.pr_credit == 1826 - 9


def test_crown_servant_absence_counts_as_presence():
    data = ApplicantInput(
        application_date=date(2026, 10, 19),
        pr_date=date(2020, 1, 1),
        absences=[Absence(date(2025, 1, 1), date(2025, 1, 11), AbsenceReason.CROWN_SERVANT)],
    )
    res = calculate(data)
    assert res.pr_credit == 1826
    assert res.crown_servant_days == 9


def test_pre_pr_half_credit_and_cap():
    app = date(2026, 10, 19)
    pr_date = date(2024, 1, 1)
    data = ApplicantInput(
        application_date=app,
        pr_date=pr_date,
        pre_pr_periods=[PrePRPeriod(Period(date(2015, 1, 1), pr_date - timedelta(days=1)))],
    )
    res = calculate(data)
    # Window start 2021-10-19 to 2023-12-31 = 804 days -> 402 raw credit, capped at 365.
    assert res.pre_pr_days_in_canada == 804
    assert res.pre_pr_credit_raw == 402
    assert res.pre_pr_credit == 365


def test_excluded_period_not_counted():
    data = ApplicantInput(
        application_date=date(2026, 10, 19),
        pr_date=date(2020, 1, 1),
        excluded_periods=[Period(date(2025, 3, 1), date(2025, 3, 10))],
    )
    res = calculate(data)
    assert res.excluded_days == 10
    assert res.pr_credit == 1826 - 10


def test_notebook_example():
    """Reproduces the example from the original notebook in this repo."""
    data = ApplicantInput(
        application_date=date(2026, 2, 14),
        pr_date=date(2023, 2, 14),
        absences=[Absence(date(2024, 12, 7), date(2024, 12, 21))],
        pre_pr_periods=[
            PrePRPeriod(Period(date(2021, 7, 6), date(2022, 9, 30))),
            PrePRPeriod(Period(date(2022, 12, 1), date(2023, 2, 13))),
        ],
    )
    res = calculate(data)
    assert res.pr_days_in_window == 1096
    assert res.pr_credit == 1096 - 13
    assert res.pre_pr_credit == pytest.approx(263.5)  # 527 days * 0.5
    assert res.eligible


# ------------------------------------------------------- earliest eligibility


def test_earliest_eligible_date_with_no_pre_pr():
    pr_date = date(2025, 1, 1)
    data = ApplicantInput(application_date=date(2026, 1, 1), pr_date=pr_date)
    assert earliest_eligible_date(data, start_from=date(2026, 1, 1)) == pr_date + timedelta(
        days=REQUIRED_DAYS
    )


def test_earliest_eligible_date_matches_calculate():
    data = ApplicantInput(
        application_date=date(2026, 1, 1),
        pr_date=date(2024, 6, 1),
        absences=[Absence(date(2025, 2, 1), date(2025, 3, 1))],
        pre_pr_periods=[PrePRPeriod(Period(date(2022, 1, 1), date(2024, 5, 31)))],
    )
    found = earliest_eligible_date(data, start_from=date(2026, 1, 1))
    assert found is not None
    on = calculate(ApplicantInput(found, data.pr_date, data.absences, data.pre_pr_periods))
    before = calculate(
        ApplicantInput(found - timedelta(days=1), data.pr_date, data.absences, data.pre_pr_periods)
    )
    assert on.eligible and not before.eligible


# ---------------------------------------------------------------- validation


def test_validate_flags_bad_input():
    data = ApplicantInput(
        application_date=date(2025, 1, 1),
        pr_date=date(2025, 6, 1),
        absences=[
            Absence(date(2024, 1, 1), date(2024, 1, 10)),
            Absence(date(2024, 1, 5), date(2024, 1, 20)),
        ],
    )
    errors = validate(data)
    assert any("PR date" in e for e in errors)
    assert any("overlap" in e for e in errors)


def test_validate_accepts_good_input():
    data = ApplicantInput(application_date=date(2026, 1, 1), pr_date=date(2022, 1, 1))
    assert validate(data) == []


def test_period_editor_csv_round_trip():
    from physical_presence.period_editor import PeriodRow, parse_csv, row_days

    csv = b"start,end,category,note\n2025-01-01,2025-01-10,,Paris\n"
    rows = parse_csv(csv, default_category="Personal")
    assert rows == [PeriodRow(date(2025, 1, 1), date(2025, 1, 10), "Personal", "Paris")]
    assert row_days(rows[0]) == 10
    assert row_days(rows[0], count_endpoints=False) == 8


def test_parse_csv_requires_columns():
    from physical_presence.period_editor import parse_csv

    with pytest.raises(ValueError, match="missing"):
        parse_csv(b"from,to\n2025-01-01,2025-01-02\n", default_category="")
