"""Canadian citizenship physical presence calculator."""

from physical_presence.calculator import (
    Absence,
    AbsenceReason,
    ApplicantInput,
    CalculationResult,
    Period,
    PrePRPeriod,
    PrePRStatus,
    calculate,
    earliest_eligible_date,
    eligibility_window,
    validate,
)

__all__ = [
    "Absence",
    "AbsenceReason",
    "ApplicantInput",
    "CalculationResult",
    "Period",
    "PrePRPeriod",
    "PrePRStatus",
    "calculate",
    "earliest_eligible_date",
    "eligibility_window",
    "validate",
]
