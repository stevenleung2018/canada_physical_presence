"""Reusable Shiny module for editing a list of date periods.

Used for absences, pre-PR status periods and excluded periods so the
add / remove / import behaviour is written once.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

import pandas as pd
from shiny import module, reactive, render, req, ui

CSV_COLUMNS = ["start", "end", "category", "note"]


@dataclass(frozen=True)
class PeriodRow:
    """A single row in a period editor."""

    start: date
    end: date
    category: str = ""
    note: str = ""


def row_days(row: PeriodRow, count_endpoints: bool = True) -> int:
    """Number of days in a row; excluding endpoints models a trip's full days away."""
    span = (row.end - row.start).days + 1
    return span if count_endpoints else max(span - 2, 0)


def rows_to_frame(
    rows: list[PeriodRow], labels: dict[str, str], count_endpoints: bool = True
) -> pd.DataFrame:
    """Convert rows to a display DataFrame using ``labels`` as column headers."""
    days_label = labels.get("days", "Days")
    return pd.DataFrame(
        [
            {
                labels["start"]: r.start.isoformat(),
                labels["end"]: r.end.isoformat(),
                labels["category"]: r.category,
                labels["note"]: r.note,
                days_label: row_days(r, count_endpoints),
            }
            for r in rows
        ],
        columns=[labels["start"], labels["end"], labels["category"], labels["note"], days_label],
    )


def parse_csv(content: bytes, default_category: str) -> list[PeriodRow]:
    """Parse an uploaded CSV with columns start,end[,category][,note]."""
    frame = pd.read_csv(io.BytesIO(content), dtype=str).fillna("")
    frame.columns = [c.strip().lower() for c in frame.columns]
    missing = {"start", "end"} - set(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing required column(s): {', '.join(sorted(missing))}.")
    rows = []
    for idx, rec in frame.iterrows():
        start = pd.to_datetime(rec["start"]).date()
        end = pd.to_datetime(rec["end"]).date()
        if end < start:
            raise ValueError(f"Row {idx + 2}: end date is before start date.")
        rows.append(
            PeriodRow(
                start=start,
                end=end,
                category=str(rec.get("category", "")) or default_category,
                note=str(rec.get("note", "")),
            )
        )
    return rows


@module.ui
def period_editor_ui(
    range_label: str,
    categories: list[str] | None = None,
    category_label: str = "Type",
    note_label: str = "Note",
    help_text: str = "",
):
    controls = [ui.input_date_range("range", range_label, start=date.today(), end=date.today())]
    if categories:
        controls.append(ui.input_select("category", category_label, choices=categories))
    controls.append(ui.input_text("note", note_label, placeholder="Optional"))

    return ui.TagList(
        ui.p(help_text, class_="text-muted small") if help_text else None,
        ui.layout_columns(*controls, col_widths={"sm": 12, "lg": [5, 4, 3][: len(controls)]}),
        ui.div(
            ui.input_action_button("add", "Add", class_="btn-primary btn-sm"),
            ui.input_action_button("remove", "Remove selected", class_="btn-outline-secondary btn-sm"),
            ui.input_action_button("clear", "Clear all", class_="btn-outline-danger btn-sm"),
            class_="d-flex gap-2 mb-2 flex-wrap",
        ),
        ui.output_ui("error"),
        ui.output_data_frame("table"),
        ui.accordion(
            ui.accordion_panel(
                "Import / export CSV",
                ui.p(
                    "Columns: start, end (YYYY-MM-DD), optional category and note.",
                    class_="small text-muted",
                ),
                ui.input_file("upload", None, accept=[".csv"], button_label="Import CSV"),
                ui.download_button("download", "Export CSV", class_="btn-sm"),
            ),
            open=False,
            class_="mt-2",
        ),
    )


@module.server
def period_editor_server(
    input,
    output,
    session,
    labels: dict[str, str],
    default_category: str = "",
    filename: str = "periods.csv",
    count_endpoints: bool = True,
):
    """Returns a reactive.value holding the current list of PeriodRow."""
    rows: reactive.Value[list[PeriodRow]] = reactive.value([])
    error_msg: reactive.Value[str] = reactive.value("")

    def _category() -> str:
        try:
            return input.category()
        except Exception:  # module created without a category selector
            return default_category

    @reactive.effect
    @reactive.event(input.add)
    def _add():
        date_range = input.range()
        if isinstance(date_range, dict):
            start, end = date_range.get("start"), date_range.get("end")
        else:
            start, end = date_range
        if start is None or end is None:
            error_msg.set("Please choose both dates.")
            return
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)
        if end < start:
            error_msg.set("The end date must be on or after the start date.")
            return
        error_msg.set("")
        new = PeriodRow(start=start, end=end, category=_category(), note=input.note().strip())
        rows.set(sorted([*rows(), new], key=lambda r: r.start))
        ui.update_text("note", value="")

    @reactive.effect
    @reactive.event(input.remove)
    def _remove():
        selected = set(table.cell_selection()["rows"])
        if not selected:
            error_msg.set("Select one or more rows in the table to remove.")
            return
        error_msg.set("")
        rows.set([r for i, r in enumerate(rows()) if i not in selected])

    @reactive.effect
    @reactive.event(input.clear)
    def _clear():
        error_msg.set("")
        rows.set([])

    @reactive.effect
    @reactive.event(input.upload)
    def _upload():
        files = req(input.upload())
        try:
            with open(files[0]["datapath"], "rb") as fh:
                imported = parse_csv(fh.read(), default_category)
        except Exception as exc:  # surface any parsing problem to the user
            error_msg.set(f"Could not import CSV: {exc}")
            return
        error_msg.set("")
        rows.set(sorted([*rows(), *imported], key=lambda r: r.start))
        ui.notification_show(f"Imported {len(imported)} row(s).", type="message")

    @render.ui
    def error():
        msg = error_msg()
        return ui.div(msg, class_="alert alert-warning py-1 small") if msg else None

    @render.data_frame
    def table():
        return render.DataGrid(
            rows_to_frame(rows(), labels, count_endpoints), selection_mode="rows", width="100%"
        )

    @render.download_button(filename=filename, media_type="text/csv")
    def download():
        frame = pd.DataFrame(
            [
                {
                    "start": r.start.isoformat(),
                    "end": r.end.isoformat(),
                    "category": r.category,
                    "note": r.note,
                }
                for r in rows()
            ],
            columns=CSV_COLUMNS,
        )
        yield frame.to_csv(index=False)

    return rows
