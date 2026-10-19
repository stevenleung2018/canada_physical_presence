"""Shiny for Python app: Canadian citizenship physical presence calculator.

Run locally with:
    shiny run --reload app.py
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from shiny import App, reactive, render, ui

from physical_presence import (
    Absence,
    AbsenceReason,
    ApplicantInput,
    CalculationResult,
    Period,
    PrePRPeriod,
    PrePRStatus,
    calculate,
    earliest_eligible_date,
    validate,
)
from physical_presence.calculator import PRE_PR_MAX_CREDIT, REQUIRED_DAYS
from physical_presence.period_editor import PeriodRow, period_editor_server, period_editor_ui

OFFICIAL_CALCULATOR_URL = "https://eservices.cic.gc.ca/rescalc/resCalcStartNew.do?lang=en"
ELIGIBILITY_URL = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/"
    "canadian-citizenship/become-canadian-citizen/eligibility.html"
)

EXCLUDED_CATEGORIES = [
    "Prison / jail",
    "Parole",
    "Probation",
    "Waiting for refugee claim decision",
    "Other",
]

ABSENCE_LABELS = {
    "start": "Departure",
    "end": "Return",
    "category": "Reason",
    "note": "Destination",
    "days": "Days absent",
}
PRE_PR_LABELS = {"start": "From", "end": "To", "category": "Status", "note": "Note"}
EXCLUDED_LABELS = {"start": "From", "end": "To", "category": "Type", "note": "Note"}


# --------------------------------------------------------------------------- UI


def _fmt_days(value: float) -> str:
    return f"{value:,.1f}".rstrip("0").rstrip(".")


app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.h5("Key dates"),
        ui.input_date(
            "application_date",
            "Application (signature) date",
            value=date.today(),
        ),
        ui.input_date(
            "pr_date",
            "Date you became a permanent resident",
            value=date.today() - timedelta(days=3 * 365),
        ),
        ui.output_ui("window_text"),
        ui.hr(),
        ui.p(
            "Unofficial tool. Always confirm with the ",
            ui.a("official IRCC calculator", href=OFFICIAL_CALCULATOR_URL, target="_blank"),
            " before applying.",
            class_="small text-muted",
        ),
        width=320,
    ),
    ui.output_ui("validation_messages"),
    ui.layout_column_wrap(
        ui.value_box("Physical presence", ui.output_text("total_days"), ui.output_text("status_text")),
        ui.value_box("As a permanent resident", ui.output_text("pr_credit"), "1 day per day in Canada"),
        ui.value_box(
            "Before PR", ui.output_text("pre_pr_credit"), f"½ day each, max {int(PRE_PR_MAX_CREDIT)}"
        ),
        ui.value_box("Earliest eligible date", ui.output_text("earliest_date"), "If no further trips"),
        fill=False,
    ),
    ui.navset_card_underline(
        ui.nav_panel(
            "Absences",
            period_editor_ui(
                "absences",
                range_label="Departure and return dates",
                categories=[r.value for r in AbsenceReason],
                category_label="Reason",
                note_label="Destination",
                help_text=(
                    "Add every trip outside Canada. The day you leave and the day you "
                    "return both count as days in Canada."
                ),
            ),
        ),
        ui.nav_panel(
            "Before PR",
            period_editor_ui(
                "pre_pr",
                range_label="Period in Canada with status",
                categories=[s.value for s in PrePRStatus],
                category_label="Status",
                help_text=(
                    "Periods in Canada as a temporary resident or protected person before you "
                    "became a PR. Protected-person time counts from the approval date."
                ),
            ),
        ),
        ui.nav_panel(
            "Excluded periods",
            period_editor_ui(
                "excluded",
                range_label="Period",
                categories=EXCLUDED_CATEGORIES,
                help_text=(
                    "Time in prison, on parole, on probation, or waiting for a refugee claim "
                    "decision does not count toward physical presence."
                ),
            ),
        ),
        ui.nav_panel(
            "Breakdown",
            ui.output_data_frame("breakdown"),
        ),
        ui.nav_panel(
            "Rules",
            ui.markdown(
                f"""
- You need at least **{REQUIRED_DAYS:,} days** in Canada during the **5 years** right
  before you sign your application.
- Each day as a **permanent resident** in Canada counts as **1 day**.
- Each day in Canada **before PR** as a temporary resident or protected person counts as
  **½ day**, up to a maximum of **{int(PRE_PR_MAX_CREDIT)} days**.
- Days employed outside Canada as a **Crown servant** (or as a family member of one) while
  a PR count as 1 day.
- Time in **prison, on parole or on probation** does not count.
- Apply with a buffer above {REQUIRED_DAYS:,} days in case of calculation differences.

Source: [IRCC — Who can apply]({ELIGIBILITY_URL})
"""
            ),
        ),
    ),
    title="Canadian Citizenship Physical Presence Calculator",
    fillable=False,
)


# ----------------------------------------------------------------------- server


def _to_input(
    application_date: date,
    pr_date: date,
    absences: list[PeriodRow],
    pre_pr: list[PeriodRow],
    excluded: list[PeriodRow],
) -> ApplicantInput:
    """Map UI rows onto the calculator's domain objects."""
    return ApplicantInput(
        application_date=application_date,
        pr_date=pr_date,
        absences=[Absence(r.start, r.end, AbsenceReason(r.category), destination=r.note) for r in absences],
        pre_pr_periods=[PrePRPeriod(Period(r.start, r.end), PrePRStatus(r.category)) for r in pre_pr],
        excluded_periods=[Period(r.start, r.end) for r in excluded],
    )


def server(input, output, session):
    absences = period_editor_server(
        "absences",
        labels=ABSENCE_LABELS,
        default_category=AbsenceReason.PERSONAL.value,
        filename="absences.csv",
        count_endpoints=False,
    )
    pre_pr = period_editor_server(
        "pre_pr",
        labels=PRE_PR_LABELS,
        default_category=PrePRStatus.TEMPORARY_RESIDENT.value,
        filename="pre_pr_periods.csv",
    )
    excluded = period_editor_server(
        "excluded",
        labels=EXCLUDED_LABELS,
        default_category=EXCLUDED_CATEGORIES[0],
        filename="excluded_periods.csv",
    )

    @reactive.calc
    def applicant() -> ApplicantInput | None:
        app_date, pr_date = input.application_date(), input.pr_date()
        if app_date is None or pr_date is None:
            return None
        return _to_input(app_date, pr_date, absences(), pre_pr(), excluded())

    @reactive.calc
    def errors() -> list[str]:
        data = applicant()
        return ["Please enter both dates."] if data is None else validate(data)

    @reactive.calc
    def result() -> CalculationResult | None:
        data = applicant()
        return calculate(data) if data is not None and not errors() else None

    @reactive.calc
    def earliest() -> date | None:
        data = applicant()
        if data is None or errors():
            return None
        return earliest_eligible_date(data, start_from=max(date.today(), data.pr_date + timedelta(days=1)))

    @render.ui
    def window_text():
        res = result()
        if res is None:
            return None
        return ui.p(
            ui.strong("Eligibility period"),
            ui.br(),
            f"{res.window.start:%Y-%m-%d} to {res.window.end:%Y-%m-%d}",
            ui.br(),
            f"({res.window.days:,} days)",
            class_="small",
        )

    @render.ui
    def validation_messages():
        msgs = errors()
        if not msgs:
            return None
        return ui.div(ui.tags.ul(*[ui.tags.li(m) for m in msgs]), class_="alert alert-danger")

    @render.text
    def total_days():
        res = result()
        return "—" if res is None else f"{_fmt_days(res.total)} / {REQUIRED_DAYS:,}"

    @render.text
    def status_text():
        res = result()
        if res is None:
            return ""
        if res.eligible:
            return f"Meets requirement (+{_fmt_days(res.surplus)} days)"
        return f"Short by {_fmt_days(res.shortfall)} days"

    @render.text
    def pr_credit():
        res = result()
        return "—" if res is None else f"{res.pr_credit:,}"

    @render.text
    def pre_pr_credit():
        res = result()
        return "—" if res is None else _fmt_days(res.pre_pr_credit)

    @render.text
    def earliest_date():
        if result() is None:
            return "—"
        found = earliest()
        if found is None:
            return "Not within 6 years"
        return "Today" if found <= date.today() else f"{found:%Y-%m-%d}"

    @render.data_frame
    def breakdown():
        res = result()
        if res is None:
            return pd.DataFrame()
        rows = [
            ("Eligibility period (days)", res.window.days),
            ("Days as PR within period", res.pr_days_in_window),
            ("Days absent as PR (excluding departure/return days)", res.pr_days_absent),
            ("Crown servant days abroad counted", res.crown_servant_days),
            ("Excluded days (prison, parole, probation, etc.)", res.excluded_days),
            ("PR credit", res.pr_credit),
            ("Pre-PR days in Canada with status", res.pre_pr_days_in_canada),
            ("Pre-PR credit before cap (½ per day)", _fmt_days(res.pre_pr_credit_raw)),
            (f"Pre-PR credit after {int(PRE_PR_MAX_CREDIT)}-day cap", _fmt_days(res.pre_pr_credit)),
            ("Total physical presence", _fmt_days(res.total)),
            ("Required", REQUIRED_DAYS),
        ]
        frame = pd.DataFrame(rows, columns=["Item", "Days"])
        frame["Days"] = [v if isinstance(v, str) else _fmt_days(v) for v in frame["Days"]]
        return render.DataGrid(frame, width="100%")


app = App(app_ui, server)
