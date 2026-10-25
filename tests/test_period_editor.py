"""Tests for period editor parsing, display helpers, and Shiny behavior."""

from datetime import date

import pandas as pd
import pytest
from shiny import App, render, ui
from shiny.testmode import export_test_values
from shiny.testserver import test_server

from physical_presence.period_editor import (
    PeriodRow,
    parse_csv,
    period_editor_server,
    period_editor_ui,
    row_days,
    rows_to_frame,
)

LABELS = {
    "start": "From",
    "end": "To",
    "category": "Reason",
    "note": "Details",
    "days": "Duration",
}


def test_row_days_inclusive_and_exclusive_for_multiday_trip():
    row = PeriodRow(date(2025, 1, 1), date(2025, 1, 10))

    assert row_days(row) == 10
    assert row_days(row, count_endpoints=False) == 8


def test_row_days_returns_zero_for_same_day_when_excluding_endpoints():
    row = PeriodRow(date(2025, 1, 1), date(2025, 1, 1))

    assert row_days(row, count_endpoints=False) == 0


def test_row_days_returns_one_for_same_day_when_inclusive():
    row = PeriodRow(date(2025, 1, 1), date(2025, 1, 1))

    assert row_days(row) == 1


def test_rows_to_frame_uses_custom_labels_and_inclusive_days():
    rows = [PeriodRow(date(2025, 1, 1), date(2025, 1, 3), "Travel", "Family visit")]

    frame = rows_to_frame(rows, LABELS)

    assert list(frame.columns) == ["From", "To", "Reason", "Details", "Duration"]
    assert frame.to_dict("records") == [
        {
            "From": "2025-01-01",
            "To": "2025-01-03",
            "Reason": "Travel",
            "Details": "Family visit",
            "Duration": 3,
        }
    ]


def test_rows_to_frame_can_use_default_days_label_and_exclude_endpoints():
    row = PeriodRow(date(2025, 1, 1), date(2025, 1, 3))
    labels = {"start": "Start", "end": "End", "category": "Type", "note": "Note"}

    frame = rows_to_frame([row], labels, count_endpoints=False)

    assert list(frame.columns) == ["Start", "End", "Type", "Note", "Days"]
    assert frame.loc[0, "Days"] == 1


def test_rows_to_frame_empty_result_has_expected_columns():
    frame = rows_to_frame([], LABELS)

    assert frame.empty
    assert list(frame.columns) == ["From", "To", "Reason", "Details", "Duration"]


def test_parse_csv_normalizes_headers_and_optional_fields():
    content = b" START , END , CATEGORY , NOTE \n2025-01-01,2025-01-03,Travel,Family visit\n"

    rows = parse_csv(content, default_category="Personal")

    assert rows == [PeriodRow(date(2025, 1, 1), date(2025, 1, 3), "Travel", "Family visit")]


def test_parse_csv_applies_default_category_and_empty_note_when_missing():
    rows = parse_csv(b"start,end\n2025-01-01,2025-01-02\n", default_category="Personal")

    assert rows == [PeriodRow(date(2025, 1, 1), date(2025, 1, 2), "Personal", "")]


def test_parse_csv_applies_default_category_when_category_is_blank():
    rows = parse_csv(
        b"start,end,category,note\n2025-01-01,2025-01-02,,note\n",
        default_category="Personal",
    )

    assert rows[0].category == "Personal"
    assert rows[0].note == "note"


def test_parse_csv_preserves_explicit_empty_default_category():
    rows = parse_csv(
        b"start,end,category,note\n2025-01-01,2025-01-02,,note\n",
        default_category="",
    )

    assert rows[0].category == ""


def test_parse_csv_parses_multiple_rows_in_input_order():
    rows = parse_csv(
        b"start,end,category,note\n2025-02-01,2025-02-02,Work,second\n2025-01-01,2025-01-03,Travel,first\n",
        default_category="",
    )

    assert [row.start for row in rows] == [date(2025, 2, 1), date(2025, 1, 1)]


def test_parse_csv_accepts_one_day_range():
    rows = parse_csv(b"start,end\n2024-02-29,2024-02-29\n", default_category="")

    assert rows == [PeriodRow(date(2024, 2, 29), date(2024, 2, 29))]


@pytest.mark.parametrize(
    "content",
    [
        b"start\n2025-01-01\n",
        b"end\n2025-01-02\n",
        b"from,to\n2025-01-01,2025-01-02\n",
    ],
)
def test_parse_csv_requires_start_and_end_columns(content):
    with pytest.raises(ValueError, match="missing required column"):
        parse_csv(content, default_category="")


def test_parse_csv_reports_row_number_for_reversed_dates():
    content = b"start,end\n2025-01-01,2025-01-02\n2025-01-04,2025-01-03\n"

    with pytest.raises(ValueError, match=r"Row 3: end date is before start date"):
        parse_csv(content, default_category="")


def test_parse_csv_rejects_invalid_end_date():
    with pytest.raises((ValueError, TypeError)):
        parse_csv(b"start,end\n2025-01-01,not-a-date\n", default_category="")


def test_parse_csv_rejects_empty_upload():
    with pytest.raises(pd.errors.EmptyDataError):
        parse_csv(b"", default_category="")


def test_period_editor_ui_without_categories_and_help_text():
    result = period_editor_ui("editor", "Date range", help_text="Include every period.")

    assert result is not None
    rendered = str(result)
    assert "Date range" in rendered
    assert "Include every period." in rendered
    assert "Add" in rendered
    assert "Remove selected" in rendered
    assert "Clear all" in rendered
    assert "Import / export CSV" in rendered


def test_period_editor_ui_with_categories():
    result = period_editor_ui(
        "editor",
        "Date range",
        categories=["Personal", "Crown servant"],
        category_label="Absence type",
        note_label="Destination",
    )

    rendered = str(result)
    assert "Absence type" in rendered
    assert "Personal" in rendered
    assert "Crown servant" in rendered
    assert "Destination" in rendered


def _period_editor_app(categories=None, initial_rows=()):
    def server(input, output, session):
        rows = period_editor_server(
            "editor",
            labels=LABELS,
            default_category="Personal",
            filename="trips.csv",
            count_endpoints=False,
        )
        rows.set(list(initial_rows))
        export_test_values(
            rows=lambda: [
                (row.start.isoformat(), row.end.isoformat(), row.category, row.note) for row in rows()
            ]
        )

        @render.text
        def row_count():
            return str(len(rows()))

    app_ui = ui.page_fluid(period_editor_ui("editor", "Dates", categories=categories))
    return App(app_ui, server)


def test_period_editor_server_adds_sorted_rows_and_trims_note():
    with test_server(_period_editor_app()) as server:
        server.set_inputs(
            **{
                "editor-range": {"start": "2025-02-01", "end": "2025-02-03"},
                "editor-category": "Work",
                "editor-note": "  conference  ",
                "editor-add": 1,
            }
        )
        server.set_inputs(
            **{
                "editor-range": {"start": "2025-01-01", "end": "2025-01-01"},
                "editor-category": "Personal",
                "editor-note": "",
                "editor-add": 2,
            }
        )

        assert server.get_output("row_count") == "2"
        assert server.get_export("rows").value == [
            ["2025-01-01", "2025-01-01", "Personal", ""],
            ["2025-02-01", "2025-02-03", "Work", "conference"],
        ]


def test_period_editor_server_clear_removes_all_rows():
    initial = [PeriodRow(date(2025, 1, 1), date(2025, 1, 2), "Personal", "")]
    with test_server(_period_editor_app(categories=["Personal"], initial_rows=initial)) as server:
        server.set_inputs(**{"editor-clear": 1})

        assert server.get_output("row_count") == "0"
        assert server.get_export("rows").value == []


def test_period_editor_server_rejects_missing_dates_without_adding_row():
    with test_server(_period_editor_app()) as server:
        server.set_inputs(**{"editor-range": {"start": None, "end": None}, "editor-add": 1})

        assert server.get_output("row_count") == "0"
        assert "Please choose both dates." in str(server.get_output("editor-error"))


def test_period_editor_server_rejects_reversed_dates():
    with test_server(_period_editor_app()) as server:
        server.set_inputs(
            **{
                "editor-range": {"start": "2025-01-02", "end": "2025-01-01"},
                "editor-add": 1,
            }
        )

        assert server.get_output("row_count") == "0"
        assert "The end date must be on or after the start date." in str(server.get_output("editor-error"))


def test_period_editor_server_uses_default_category_without_selector():
    with test_server(_period_editor_app(categories=None)) as server:
        server.set_inputs(
            **{
                "editor-range": {"start": "2025-01-01", "end": "2025-01-02"},
                "editor-note": "",
                "editor-add": 1,
            }
        )

        assert server.get_export("rows").value == [["2025-01-01", "2025-01-02", "Personal", ""]]


def test_period_editor_server_accepts_pair_shaped_date_range():
    with test_server(_period_editor_app(categories=["Personal"])) as server:
        server.set_inputs(
            **{
                "editor-range": ["2025-01-01", "2025-01-02"],
                "editor-note": "",
                "editor-add": 1,
            }
        )

        assert server.get_export("rows").value == [["2025-01-01", "2025-01-02", "Personal", ""]]


def test_period_editor_server_imports_csv_and_sorts_rows(tmp_path):
    initial = [PeriodRow(date(2025, 3, 1), date(2025, 3, 2), "Personal", "existing")]
    upload_path = tmp_path / "periods.csv"
    upload_path.write_bytes(b"start,end,category,note\n2025-01-01,2025-01-02,Work,imported\n")
    with test_server(_period_editor_app(categories=["Personal"], initial_rows=initial)) as server:
        server.set_inputs(
            **{
                "editor-upload": [
                    {
                        "name": "periods.csv",
                        "size": upload_path.stat().st_size,
                        "type": "text/csv",
                        "datapath": str(upload_path),
                    }
                ]
            }
        )

        assert server.get_export("rows").value == [
            ["2025-01-01", "2025-01-02", "Work", "imported"],
            ["2025-03-01", "2025-03-02", "Personal", "existing"],
        ]


def test_period_editor_server_surfaces_csv_import_errors(tmp_path):
    upload_path = tmp_path / "invalid.csv"
    upload_path.write_bytes(b"not,a,period\n")
    with test_server(_period_editor_app()) as server:
        server.set_inputs(
            **{
                "editor-upload": [
                    {
                        "name": "invalid.csv",
                        "size": upload_path.stat().st_size,
                        "type": "text/csv",
                        "datapath": str(upload_path),
                    }
                ]
            }
        )

        assert "Could not import CSV" in str(server.get_output("editor-error"))
