"""Core physical presence calculation logic for Canadian citizenship.

This module is UI-agnostic and has no Shiny dependency so it can be unit
tested and reused independently.

Rules implemented (adult grant of citizenship, Citizenship Act s.5(1)(c)):

* The eligibility period is the 5 years immediately before the application
  (signature) date.
* At least 1,095 days of physical presence are required.
* Each day in Canada as a permanent resident (PR) counts as 1 day.
* Each day in Canada *before* becoming a PR, while a temporary resident or
  protected person, counts as 0.5 day, to a maximum credit of 365 days.
* Days employed outside Canada as a Crown servant (or as a Crown servant's
  family member) while a PR count as 1 day.
* Days in prison, on parole, or on probation (and, for pre-PR time, days
  waiting on a refugee claim decision) do not count.
* Following the official IRCC calculator, the day you leave Canada and the
  day you return are both counted as days in Canada.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

REQUIRED_DAYS = 1095
PRE_PR_MAX_CREDIT = 365.0
PRE_PR_CREDIT_RATE = 0.5
ELIGIBILITY_YEARS = 5


class AbsenceReason(str, Enum):
    """Why the applicant was outside Canada."""

    PERSONAL = "Personal / travel / other"
    CROWN_SERVANT = "Crown servant (or family member) abroad"


class PrePRStatus(str, Enum):
    """Qualifying status held in Canada before becoming a permanent resident."""

    TEMPORARY_RESIDENT = "Temporary resident (visitor, student, worker, TRP)"
    PROTECTED_PERSON = "Protected person"


@dataclass(frozen=True)
class Period:
    """An inclusive date range."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"Period end {self.end} is before start {self.start}.")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def overlaps(self, other: Period) -> bool:
        return self.start <= other.end and other.start <= self.end


@dataclass(frozen=True)
class Absence:
    """A trip outside Canada, from departure date to return date."""

    departure: date
    return_date: date
    reason: AbsenceReason = AbsenceReason.PERSONAL
    destination: str = ""

    def __post_init__(self) -> None:
        if self.return_date < self.departure:
            raise ValueError("Return date cannot be before departure date.")

    @property
    def days_absent(self) -> int:
        """Full days outside Canada (departure and return days excluded)."""
        return max((self.return_date - self.departure).days - 1, 0)

    def absent_on(self, day: date) -> bool:
        return self.departure < day < self.return_date


@dataclass(frozen=True)
class PrePRPeriod:
    """A period of qualifying status in Canada before becoming a PR."""

    period: Period
    status: PrePRStatus = PrePRStatus.TEMPORARY_RESIDENT


@dataclass
class ApplicantInput:
    """Everything needed to compute physical presence."""

    application_date: date
    pr_date: date
    absences: Sequence[Absence] = field(default_factory=list)
    pre_pr_periods: Sequence[PrePRPeriod] = field(default_factory=list)
    excluded_periods: Sequence[Period] = field(default_factory=list)


@dataclass(frozen=True)
class CalculationResult:
    """Outcome of a physical presence calculation."""

    window: Period
    pr_days_in_window: int
    pr_days_absent: int
    crown_servant_days: int
    excluded_days: int
    pr_credit: int
    pre_pr_days_in_canada: int
    pre_pr_credit_raw: float
    pre_pr_credit: float
    total: float
    required: int = REQUIRED_DAYS

    @property
    def eligible(self) -> bool:
        return self.total >= self.required

    @property
    def shortfall(self) -> float:
        return max(self.required - self.total, 0.0)

    @property
    def surplus(self) -> float:
        return max(self.total - self.required, 0.0)


def subtract_years(day: date, years: int) -> date:
    """Return the same calendar date ``years`` earlier (Feb 29 -> Feb 28)."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # Feb 29 in a non-leap target year
        return day.replace(year=day.year - years, day=28)


def eligibility_window(application_date: date) -> Period:
    """The 5-year period immediately before the application date."""
    start = subtract_years(application_date, ELIGIBILITY_YEARS)
    return Period(start, application_date - timedelta(days=1))


def _iter_days(period: Period) -> Iterable[date]:
    for offset in range(period.days):
        yield period.start + timedelta(days=offset)


def _day_credits(data: ApplicantInput, window: Period) -> dict[str, list]:
    """Classify each day of ``window``. Returns parallel lists by category."""
    pr_present, pr_absent, crown, excluded, pre_pr = [], [], [], [], []
    for day in _iter_days(window):
        is_excluded = any(p.contains(day) for p in data.excluded_periods)
        absence = next((a for a in data.absences if a.absent_on(day)), None)
        is_pr = day >= data.pr_date

        excluded.append(is_excluded)
        if is_pr:
            is_crown = absence is not None and absence.reason is AbsenceReason.CROWN_SERVANT
            pr_present.append(not is_excluded and (absence is None or is_crown))
            pr_absent.append(absence is not None and not is_crown)
            crown.append(not is_excluded and is_crown)
            pre_pr.append(False)
        else:
            has_status = any(p.period.contains(day) for p in data.pre_pr_periods)
            pre_pr.append(has_status and absence is None and not is_excluded)
            pr_present.append(False)
            pr_absent.append(False)
            crown.append(False)
    return {
        "pr_present": pr_present,
        "pr_absent": pr_absent,
        "crown": crown,
        "excluded": excluded,
        "pre_pr": pre_pr,
    }


def validate(data: ApplicantInput) -> list[str]:
    """Return a list of human-readable problems with the input (empty if OK)."""
    errors: list[str] = []
    if data.pr_date >= data.application_date:
        errors.append("The PR date must be before the application date.")
    for a in data.absences:
        if a.departure >= data.application_date:
            errors.append(f"Absence starting {a.departure} is on/after the application date.")
    ordered = sorted(data.absences, key=lambda a: a.departure)
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        if nxt.departure < prev.return_date:
            errors.append(
                f"Absences overlap: {prev.departure}–{prev.return_date} and "
                f"{nxt.departure}–{nxt.return_date}."
            )
    for p in data.pre_pr_periods:
        if p.period.start >= data.pr_date:
            errors.append(f"Pre-PR period starting {p.period.start} is not before the PR date.")
    return errors


def calculate(data: ApplicantInput) -> CalculationResult:
    """Compute physical presence for the eligibility window."""
    window = eligibility_window(data.application_date)
    c = _day_credits(data, window)

    pr_days_in_window = sum(1 for d in _iter_days(window) if d >= data.pr_date)
    pr_credit = sum(c["pr_present"])
    pre_pr_days = sum(c["pre_pr"])
    pre_pr_raw = pre_pr_days * PRE_PR_CREDIT_RATE
    pre_pr_credit = min(pre_pr_raw, PRE_PR_MAX_CREDIT)

    return CalculationResult(
        window=window,
        pr_days_in_window=pr_days_in_window,
        pr_days_absent=sum(c["pr_absent"]),
        crown_servant_days=sum(c["crown"]),
        excluded_days=sum(c["excluded"]),
        pr_credit=pr_credit,
        pre_pr_days_in_canada=pre_pr_days,
        pre_pr_credit_raw=pre_pr_raw,
        pre_pr_credit=pre_pr_credit,
        total=pr_credit + pre_pr_credit,
    )


def earliest_eligible_date(
    data: ApplicantInput, start_from: date, horizon_days: int = 6 * 366
) -> date | None:
    """Earliest application date on/after ``start_from`` that meets the requirement.

    Assumes the applicant stays in Canada from now on except for absences that
    are already entered (useful for checking planned trips). Uses prefix sums
    so the search is linear in the number of days examined.
    """
    first_window_start = eligibility_window(start_from).start
    span = Period(first_window_start, start_from + timedelta(days=horizon_days))
    probe = ApplicantInput(
        application_date=span.end + timedelta(days=1),
        pr_date=data.pr_date,
        absences=data.absences,
        pre_pr_periods=data.pre_pr_periods,
        excluded_periods=data.excluded_periods,
    )
    c = _day_credits(probe, span)

    def prefix(values: list[bool]) -> list[int]:
        out = [0]
        for v in values:
            out.append(out[-1] + int(v))
        return out

    pr_prefix = prefix(c["pr_present"])
    pre_prefix = prefix(c["pre_pr"])

    candidate = start_from
    while candidate <= span.end:
        w = eligibility_window(candidate)
        lo = (w.start - span.start).days
        hi = (w.end - span.start).days + 1
        pr = pr_prefix[hi] - pr_prefix[lo]
        pre = min((pre_prefix[hi] - pre_prefix[lo]) * PRE_PR_CREDIT_RATE, PRE_PR_MAX_CREDIT)
        if candidate > data.pr_date and pr + pre >= REQUIRED_DAYS:
            return candidate
        candidate += timedelta(days=1)
    return None
