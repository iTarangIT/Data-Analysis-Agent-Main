"""Rows into a series. No model involved, so every rule here is assertable offline."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from app.forecasting.preprocessing import (
    FREQ,
    MIN_HISTORY,
    ForecastInputError,
    label,
    prepare_series,
)

TODAY = date(2026, 9, 22)
COLUMNS = ["month", "revenue"]


def months(n: int, end_month: int = 8, value=lambda i: 100 + i) -> list[list]:
    """`n` month-start dates ending at 2026-`end_month`, oldest first."""
    rows = []
    for i in range(n):
        back = n - 1 - i
        year, month = 2026 + (end_month - 1 - back) // 12, (end_month - 1 - back) % 12 + 1
        rows.append([date(year, month, 1), value(i)])
    return rows


def prepare(rows, grain="month", kind="total", columns=COLUMNS, **kwargs):
    return prepare_series(columns, rows, "month", "revenue", grain, kind, TODAY, **kwargs)


def error(rows, **kwargs) -> ForecastInputError:
    with pytest.raises(ForecastInputError) as caught:
        prepare(rows, **kwargs)
    return caught.value


class TestShapes:
    def test_date_objects_become_one_value_per_month_oldest_first(self):
        series = prepare(months(12)[::-1])

        assert [label(p) for p in series.periods][:2] == ["2025-09", "2025-10"]
        assert label(series.periods[-1]) == "2026-08"
        assert series.values.tolist() == [float(100 + i) for i in range(12)]

    def test_iso_strings_across_a_dst_change_keep_their_wall_clock_month(self):
        # Postgres timestamptz arrives through MCP JSON as strings with the session's offset,
        # which changes at DST. Converting to UTC would move April's midnight into March.
        rows = [
            [f"2026-{m:02d}-01T00:00:00{'+01:00' if m < 4 else '+02:00'}", m] for m in range(1, 9)
        ]
        rows = [[f"2025-{m:02d}-01T00:00:00+01:00", m] for m in range(9, 13)] + rows

        series = prepare(rows)

        assert "2026-04" in [label(p) for p in series.periods]
        assert len(series) == 12

    def test_decimals_and_numeric_strings_are_numbers(self):
        rows = [[r[0], Decimal("10.50") if i % 2 else "7.25"] for i, r in enumerate(months(8))]

        assert prepare(rows).values.tolist()[:2] == [7.25, 10.5]

    def test_a_datetime_is_accepted_as_well_as_a_date(self):
        rows = [[datetime(r[0].year, r[0].month, 1, 9, 30), r[1]] for r in months(8)]

        assert len(prepare(rows)) == 8


class TestDuplicatesAndGaps:
    def test_a_total_adds_up_duplicate_periods(self):
        rows = [*months(8), [date(2026, 8, 15), 50]]

        series = prepare(rows, kind="total")

        assert series.values[-1] == 107 + 50
        assert series.merged == 1

    def test_a_level_averages_duplicate_periods(self):
        rows = [*months(8), [date(2026, 8, 15), 7]]

        assert prepare(rows, kind="level").values[-1] == (107 + 7) / 2

    def test_a_missing_month_of_a_total_is_zero(self):
        rows = [r for i, r in enumerate(months(10)) if i != 4]

        series = prepare(rows, kind="total")

        assert series.values[4] == 0.0
        assert series.filled == 1

    def test_a_missing_month_of_a_level_is_interpolated(self):
        rows = [r for i, r in enumerate(months(10)) if i != 4]

        assert prepare(rows, kind="level").values[4] == 104.0

    def test_a_null_value_is_a_gap_not_a_zero_or_a_crash(self):
        rows = months(10)
        rows[4][1] = None

        series = prepare(rows, kind="level")

        assert series.values[4] == 104.0
        assert not any(v != v for v in series.values), "NaN reached the series"

    def test_the_month_still_in_progress_is_dropped(self):
        series = prepare(months(12, end_month=9))

        assert label(series.periods[-1]) == "2026-08"
        assert series.dropped_partial == "2026-09"


class TestWeeks:
    def test_weeks_start_on_monday_like_date_trunc(self):
        rows = [[date(2026, 6, 1) + timedelta(weeks=i), 1] for i in range(9)]  # nine Mondays
        rows.append([date(2026, 7, 8), 1])  # a Wednesday inside the week of 2026-07-06

        series = prepare(rows, grain="week")

        assert label(series.periods[0]) == "2026-06-01"
        assert series.merged == 1


class TestLabels:
    @pytest.mark.parametrize(
        ("grain", "start", "expected"),
        [
            ("hour", "2026-01-01 05:00", "2026-01-01T05:00"),
            ("day", "2026-07-01", "2026-07-01"),
            ("week", "2026-07-06", "2026-07-06"),
            ("month", "2026-07-01", "2026-07"),
            ("quarter", "2026-07-01", "2026Q3"),
            ("year", "2026-07-01", "2026"),
        ],
    )
    def test_each_grain_gets_its_iso_label(self, grain, start, expected):
        assert label(pd.Period(start, freq=FREQ[grain])) == expected


class TestRefusals:
    def test_a_missing_column_is_fixable_and_names_what_exists(self):
        e = error(months(8), columns=["period", "revenue"])

        assert (e.code, e.fixable) == ("missing_column", True)
        assert "period" in e.message

    def test_no_rows_cannot_be_forecast(self):
        assert (error([]).code, error([]).fixable) == ("empty", False)

    def test_text_in_the_time_column_is_fixable(self):
        e = error([["soon", 1]] * 8)

        assert (e.code, e.fixable) == ("bad_timestamps", True)

    def test_text_in_the_value_column_is_fixable_and_quoted(self):
        rows = months(8)
        rows[3][1] = "n/a"

        e = error(rows)

        assert (e.code, e.fixable) == ("not_numeric", True)
        assert "n/a" in e.message

    def test_too_little_history_cannot_be_forecast(self):
        e = error(months(MIN_HISTORY - 1))

        assert (e.code, e.fixable) == ("insufficient_history", False)

    def test_mostly_empty_periods_ask_for_a_longer_grain(self):
        rows = [r for i, r in enumerate(months(12)) if i % 2 == 0 or i == 11]

        e = error(rows)

        assert (e.code, e.fixable) == ("too_sparse", True)

    def test_a_capped_result_oldest_first_is_fixable(self):
        e = error(months(12), capped=True)

        assert (e.code, e.fixable) == ("wrong_order", True)

    def test_a_capped_result_that_was_not_grouped_is_fixable(self):
        # Cut off mid-period, the oldest month holds only part of its rows.
        rows = [[r[0].replace(day=d), 1] for r in months(12)[::-1] for d in (20, 10)]

        e = error(rows, capped=True)

        assert (e.code, e.fixable) == ("not_grouped", True)

    def test_a_capped_result_newest_first_is_used(self):
        series = prepare(months(12)[::-1], capped=True)

        assert series.capped and len(series) == 12
