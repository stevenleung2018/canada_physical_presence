"""Unit tests for the physical presence calculator."""

from datetime import date, timedelta

import pytest

from physical_presence import (
    Absence,
    AbsenceReason,
    ApplicantInput,
    Period,
    PrePRPeriod,
    PrePRStatus,
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


# ------------------------------------------- corner cases: dates and windows

APP = date(2026, 10, 19)  # window 2021-10-19 .. 2026-10-18 (1826 days)


def test_application_on_leap_day_window():
    window = eligibility_window(date(2024, 2, 29))
    assert window.start == date(2019, 2, 28)
    assert window.end == date(2024, 2, 28)


def test_pr_date_is_window_start_counts_whole_window():
    res = calculate(ApplicantInput(application_date=APP, pr_date=date(2021, 10, 19)))
    assert res.pr_days_in_window == 1826


def test_pr_date_is_last_window_day():
    res = calculate(ApplicantInput(application_date=APP, pr_date=date(2026, 10, 18)))
    assert res.pr_days_in_window == 1
    assert res.pr_credit == 1


def test_pr_date_on_application_date_gives_no_pr_days():
    res = calculate(ApplicantInput(application_date=APP, pr_date=APP))
    assert res.pr_days_in_window == 0
    assert res.total == 0
    assert not res.eligible


def test_pr_date_before_window_equals_pr_date_in_window():
    a = calculate(ApplicantInput(application_date=APP, pr_date=date(2000, 1, 1)))
    b = calculate(ApplicantInput(application_date=APP, pr_date=date(2021, 10, 19)))
    assert a.total == b.total


def test_activity_outside_window_is_ignored():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2018, 1, 1), date(2018, 6, 1))],
        excluded_periods=[Period(date(2019, 1, 1), date(2019, 12, 31))],
        pre_pr_periods=[PrePRPeriod(Period(date(2010, 1, 1), date(2014, 12, 31)))],
    )
    res = calculate(data)
    assert res.pr_days_absent == res.excluded_days == 0
    assert res.pre_pr_credit == 0
    assert res.total == 1826


def test_absence_straddling_window_start_only_counts_inside_days():
    # Away 2021-10-15 .. 2021-10-25: full absent days 10-16..10-24; in window 10-19..10-24 = 6
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2021, 10, 15), date(2021, 10, 25))],
    )
    assert calculate(data).pr_days_absent == 6


def test_absence_straddling_window_end_only_counts_inside_days():
    # Absent days 2026-10-15..2026-10-20; window ends 10-18 -> 10-15..10-18 = 4
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2026, 10, 14), date(2026, 10, 21))],
    )
    assert calculate(data).pr_days_absent == 4


# ------------------------------------------------- corner cases: absences


def test_back_to_back_trips_share_a_day_in_canada():
    # Return on 1/10 and depart on 1/10 -> that day counts in Canada.
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[
            Absence(date(2025, 1, 1), date(2025, 1, 10)),
            Absence(date(2025, 1, 10), date(2025, 1, 20)),
        ],
    )
    assert validate(data) == []
    assert calculate(data).pr_days_absent == 8 + 9


def test_one_day_gap_between_trips():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[
            Absence(date(2025, 1, 1), date(2025, 1, 5)),
            Absence(date(2025, 1, 6), date(2025, 1, 10)),
        ],
    )
    assert calculate(data).pr_days_absent == 3 + 3


def test_many_same_day_trips_cost_nothing():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2025, 1, d), date(2025, 1, d)) for d in range(1, 29)],
    )
    assert calculate(data).pr_days_absent == 0


def test_absence_longer_than_window_leaves_only_boundaries():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2020, 1, 1), date(2027, 1, 1))],
    )
    res = calculate(data)
    assert res.pr_days_absent == 1826
    assert res.pr_credit == 0
    assert not res.eligible


def test_absence_on_application_date_boundary_does_not_count_after_window():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2026, 10, 18), date(2026, 10, 30))],
    )
    assert calculate(data).pr_days_absent == 0


def test_leap_day_absence_counts_as_one_day():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2024, 2, 28), date(2024, 3, 1))],  # only Feb 29 absent
    )
    assert calculate(data).pr_days_absent == 1


def test_validate_adjacent_absences_not_flagged_but_overlapping_are():
    ok = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[
            Absence(date(2025, 1, 1), date(2025, 1, 10)),
            Absence(date(2025, 1, 10), date(2025, 1, 12)),
        ],
    )
    assert validate(ok) == []
    bad = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[
            Absence(date(2025, 1, 1), date(2025, 1, 10)),
            Absence(date(2025, 1, 9), date(2025, 1, 12)),
        ],
    )
    assert any("overlap" in e for e in validate(bad))


def test_validate_absence_on_application_date():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(APP, APP + timedelta(days=3))],
    )
    assert any("application date" in e for e in validate(data))


def test_absence_rejects_reversed_dates():
    with pytest.raises(ValueError):
        Absence(date(2025, 1, 2), date(2025, 1, 1))


# ------------------------------------- combinations: absence types x residence


def test_mixed_personal_and_crown_absences():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[
            Absence(date(2024, 1, 1), date(2024, 1, 21), AbsenceReason.PERSONAL),  # 19
            Absence(date(2024, 6, 1), date(2024, 12, 1), AbsenceReason.CROWN_SERVANT),
        ],
    )
    res = calculate(data)
    crown_days = Absence(date(2024, 6, 1), date(2024, 12, 1)).days_absent
    assert res.pr_days_absent == 19
    assert res.crown_servant_days == crown_days
    assert res.pr_credit == 1826 - 19


def test_crown_servant_absence_overlapping_excluded_period_is_not_credited():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2025, 1, 1), date(2025, 1, 11), AbsenceReason.CROWN_SERVANT)],
        excluded_periods=[Period(date(2025, 1, 1), date(2025, 1, 11))],
    )
    res = calculate(data)
    assert res.crown_servant_days == 0
    assert res.excluded_days == 11
    assert res.pr_credit == 1826 - 11


def test_personal_absence_inside_excluded_period_is_not_double_penalised():
    # Excluded days are removed from credit once; the absence is still tallied separately.
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        absences=[Absence(date(2025, 1, 1), date(2025, 1, 11))],  # 9 absent days
        excluded_periods=[Period(date(2025, 1, 1), date(2025, 1, 11))],
    )
    res = calculate(data)
    assert res.pr_credit == 1826 - 11  # 9 absent days are within the 11 excluded
    assert res.excluded_days == 11


def test_overlapping_excluded_periods_not_double_counted():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        excluded_periods=[
            Period(date(2025, 1, 1), date(2025, 1, 10)),
            Period(date(2025, 1, 5), date(2025, 1, 15)),
        ],
    )
    res = calculate(data)
    assert res.excluded_days == 15
    assert res.pr_credit == 1826 - 15


def test_excluded_period_that_covers_whole_window():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        excluded_periods=[Period(date(2000, 1, 1), date(2030, 1, 1))],
    )
    res = calculate(data)
    assert res.pr_credit == 0
    assert not res.eligible


def test_everything_combined_pr_absence_crown_excluded_prepr():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2023, 1, 1),
        absences=[
            Absence(date(2024, 1, 1), date(2024, 1, 11)),  # 9 personal
            Absence(date(2024, 3, 1), date(2024, 3, 11), AbsenceReason.CROWN_SERVANT),  # 9 crown
        ],
        excluded_periods=[Period(date(2025, 1, 1), date(2025, 1, 5))],  # 5 excluded
        pre_pr_periods=[PrePRPeriod(Period(date(2021, 1, 1), date(2022, 12, 31)))],
    )
    res = calculate(data)
    pr_days = (APP - date(2023, 1, 1)).days
    assert res.pr_days_in_window == pr_days
    assert res.pr_credit == pr_days - 9 - 5
    assert res.crown_servant_days == 9
    pre_days = (date(2022, 12, 31) - date(2021, 10, 19)).days + 1
    assert res.pre_pr_days_in_canada == pre_days
    assert res.pre_pr_credit == min(pre_days * 0.5, 365)
    assert res.total == res.pr_credit + res.pre_pr_credit


# ------------------------------------- combinations: pre-PR residences


@pytest.mark.parametrize("status", list(PrePRStatus))
def test_pre_pr_status_types_both_earn_half_credit(status):
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 10, 19),
        pre_pr_periods=[PrePRPeriod(Period(date(2025, 1, 1), date(2025, 1, 10)), status)],
    )
    res = calculate(data)
    assert res.pre_pr_days_in_canada == 10
    assert res.pre_pr_credit == 5


def test_multiple_pre_pr_periods_of_different_status_sum():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 10, 19),
        pre_pr_periods=[
            PrePRPeriod(Period(date(2023, 1, 1), date(2023, 1, 10)), PrePRStatus.TEMPORARY_RESIDENT),
            PrePRPeriod(Period(date(2024, 1, 1), date(2024, 1, 20)), PrePRStatus.PROTECTED_PERSON),
        ],
    )
    res = calculate(data)
    assert res.pre_pr_days_in_canada == 30
    assert res.pre_pr_credit == 15


def test_overlapping_pre_pr_periods_not_double_counted():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 10, 19),
        pre_pr_periods=[
            PrePRPeriod(Period(date(2024, 1, 1), date(2024, 1, 10))),
            PrePRPeriod(Period(date(2024, 1, 5), date(2024, 1, 20)), PrePRStatus.PROTECTED_PERSON),
        ],
    )
    assert calculate(data).pre_pr_days_in_canada == 20


def test_pre_pr_credit_cap_exactly_at_boundary():
    # 730 days -> 365 credit: exactly at cap
    start = date(2022, 1, 1)
    data = ApplicantInput(
        application_date=APP,
        pr_date=start + timedelta(days=730),
        pre_pr_periods=[PrePRPeriod(Period(start, start + timedelta(days=729)))],
    )
    res = calculate(data)
    assert res.pre_pr_credit_raw == 365
    assert res.pre_pr_credit == 365


def test_pre_pr_credit_cap_one_day_over_boundary():
    start = date(2022, 1, 1)
    data = ApplicantInput(
        application_date=APP,
        pr_date=start + timedelta(days=732),
        pre_pr_periods=[PrePRPeriod(Period(start, start + timedelta(days=731)))],
    )
    res = calculate(data)
    assert res.pre_pr_days_in_canada == 732
    assert res.pre_pr_credit_raw == 366
    assert res.pre_pr_credit == 365


def test_odd_number_of_pre_pr_days_gives_half_day():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 10, 19),
        pre_pr_periods=[PrePRPeriod(Period(date(2025, 1, 1), date(2025, 1, 3)))],
    )
    assert calculate(data).pre_pr_credit == 1.5


def test_pre_pr_absence_removes_pre_pr_days():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 10, 19),
        absences=[Absence(date(2025, 1, 1), date(2025, 1, 11))],  # 9 absent days
        pre_pr_periods=[PrePRPeriod(Period(date(2025, 1, 1), date(2025, 1, 20)))],
    )
    res = calculate(data)
    assert res.pre_pr_days_in_canada == 20 - 9
    assert res.pr_days_absent == 0  # pre-PR absence is not a PR absence


def test_crown_servant_absence_gives_no_pre_pr_credit():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 10, 19),
        absences=[Absence(date(2025, 1, 1), date(2025, 1, 11), AbsenceReason.CROWN_SERVANT)],
        pre_pr_periods=[PrePRPeriod(Period(date(2025, 1, 1), date(2025, 1, 20)))],
    )
    res = calculate(data)
    assert res.pre_pr_days_in_canada == 11
    assert res.crown_servant_days == 0


def test_pre_pr_excluded_period_removes_days():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 10, 19),
        excluded_periods=[Period(date(2025, 1, 1), date(2025, 1, 10))],
        pre_pr_periods=[PrePRPeriod(Period(date(2025, 1, 1), date(2025, 1, 20)))],
    )
    assert calculate(data).pre_pr_days_in_canada == 10


def test_pre_pr_gap_days_without_status_earn_nothing():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 10, 19),
        pre_pr_periods=[
            PrePRPeriod(Period(date(2024, 1, 1), date(2024, 1, 10))),
            PrePRPeriod(Period(date(2024, 1, 21), date(2024, 1, 30))),
        ],
    )
    assert calculate(data).pre_pr_days_in_canada == 20


def test_absence_straddling_pr_date_splits_between_categories():
    # Absent days 2025-01-02..2025-01-09; PR on 2025-01-06 -> 4 pre-PR, 4 PR absent days
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 1, 6),
        absences=[Absence(date(2025, 1, 1), date(2025, 1, 10))],
        pre_pr_periods=[PrePRPeriod(Period(date(2024, 12, 1), date(2025, 1, 5)))],
    )
    res = calculate(data)
    assert res.pr_days_absent == 4
    assert res.pre_pr_days_in_canada == (date(2025, 1, 5) - date(2024, 12, 1)).days + 1 - 4


def test_pre_pr_period_on_pr_date_does_not_double_count():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2025, 1, 6),
        pre_pr_periods=[PrePRPeriod(Period(date(2025, 1, 1), date(2025, 1, 10)))],
    )
    res = calculate(data)
    assert res.pre_pr_days_in_canada == 5  # Jan 1-5 only; Jan 6+ are PR days
    assert res.pr_credit == (APP - date(2025, 1, 6)).days


def test_pre_pr_credit_cannot_make_up_unlimited_shortfall():
    # 1 year of PR (365) + capped pre-PR (365) = 730 < 1095
    data = ApplicantInput(
        application_date=APP,
        pr_date=APP - timedelta(days=365),
        pre_pr_periods=[PrePRPeriod(Period(date(2021, 10, 19), APP - timedelta(days=366)))],
    )
    res = calculate(data)
    assert res.pre_pr_credit == 365
    assert res.total == 730
    assert res.shortfall == 365


def test_validate_pre_pr_period_after_pr_date():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2024, 1, 1),
        pre_pr_periods=[PrePRPeriod(Period(date(2024, 2, 1), date(2024, 3, 1)))],
    )
    assert any("Pre-PR period" in e for e in validate(data))


# -------------------------------------------------- result helpers / eligibility


def test_surplus_and_shortfall_are_mutually_exclusive():
    ok = calculate(ApplicantInput(application_date=APP, pr_date=date(2015, 1, 1)))
    assert ok.surplus == 1826 - 1095 and ok.shortfall == 0
    short = calculate(ApplicantInput(application_date=APP, pr_date=APP - timedelta(days=100)))
    assert short.surplus == 0 and short.shortfall == 995


def test_exactly_1095_via_pr_plus_pre_pr_mix():
    # 1000 PR days + 190 pre-PR days (95 credit) = 1095
    data = ApplicantInput(
        application_date=APP,
        pr_date=APP - timedelta(days=1000),
        pre_pr_periods=[
            PrePRPeriod(Period(APP - timedelta(days=1190), APP - timedelta(days=1001)))
        ],
    )
    res = calculate(data)
    assert res.total == 1095
    assert res.eligible


def test_one_day_absence_flips_eligibility():
    pr_date = APP - timedelta(days=REQUIRED_DAYS)
    base = ApplicantInput(application_date=APP, pr_date=pr_date)
    assert calculate(base).eligible
    base.absences = [Absence(date(2025, 1, 1), date(2025, 1, 3))]  # 1 absent day
    assert not calculate(base).eligible


# --------------------------------------------------- earliest_eligible_date


def test_earliest_eligible_date_already_eligible_returns_start():
    data = ApplicantInput(application_date=APP, pr_date=date(2015, 1, 1))
    assert earliest_eligible_date(data, start_from=APP) == APP


def test_earliest_eligible_date_pushed_by_future_absence():
    pr_date = date(2025, 1, 1)
    data = ApplicantInput(
        application_date=date(2026, 1, 1),
        pr_date=pr_date,
        absences=[Absence(date(2026, 6, 1), date(2026, 6, 11))],  # 9 absent days
    )
    found = earliest_eligible_date(data, start_from=date(2026, 1, 1))
    assert found == pr_date + timedelta(days=REQUIRED_DAYS + 9)


def test_earliest_eligible_date_with_pre_pr_credit_matches_calculate():
    data = ApplicantInput(
        application_date=date(2026, 1, 1),
        pr_date=date(2025, 1, 1),
        absences=[Absence(date(2025, 6, 1), date(2025, 6, 11), AbsenceReason.CROWN_SERVANT)],
        pre_pr_periods=[
            PrePRPeriod(Period(date(2022, 1, 1), date(2024, 12, 31)), PrePRStatus.PROTECTED_PERSON)
        ],
    )
    found = earliest_eligible_date(data, start_from=date(2026, 1, 1))
    assert found is not None
    for d, expected in ((found, True), (found - timedelta(days=1), False)):
        probe = ApplicantInput(d, data.pr_date, data.absences, data.pre_pr_periods)
        assert calculate(probe).eligible is expected


def test_earliest_eligible_date_none_when_never_eligible():
    data = ApplicantInput(
        application_date=APP,
        pr_date=date(2015, 1, 1),
        excluded_periods=[Period(date(2020, 1, 1), date(2040, 1, 1))],
    )
    assert earliest_eligible_date(data, start_from=APP) is None


# ------------------------------------------------------------ CSV parsing


def test_parse_csv_rejects_bad_date():
    from physical_presence.period_editor import parse_csv

    with pytest.raises(ValueError):
        parse_csv(b"start,end,category,note\nnot-a-date,2025-01-02,,\n", default_category="")


def test_row_days_single_day_period():
    from physical_presence.period_editor import PeriodRow, row_days

    row = PeriodRow(date(2025, 1, 1), date(2025, 1, 1), "Personal", "")
    assert row_days(row) == 1
    assert row_days(row, count_endpoints=False) == 0
