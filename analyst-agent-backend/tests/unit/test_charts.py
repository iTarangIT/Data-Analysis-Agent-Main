"""Chart inference. No model call, so this is fully assertable offline, which is the reason
this is a rule rather than a second question to the model."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.charts import MAX_POINTS, forecast_chart, infer_chart


class TestWhenAChartHelps:
    def test_a_month_column_and_a_number_becomes_a_line(self):
        chart = infer_chart(
            ["month", "revenue"],
            [[date(2026, 7, 1), 100], [date(2026, 8, 1), 140]],
            truncated=False,
        )

        assert chart == {"type": "line", "x": "month", "y": ["revenue"]}

    def test_a_category_and_a_number_becomes_a_bar(self):
        chart = infer_chart(["region", "units"], [["West", 10], ["East", 4]], truncated=False)

        assert chart == {"type": "bar", "x": "region", "y": ["units"]}

    def test_every_numeric_column_is_plotted(self):
        chart = infer_chart(
            ["month", "units", "revenue"],
            [[date(2026, 7, 1), 10, 250], [date(2026, 8, 1), 6, 150]],
            truncated=False,
        )

        assert chart["y"] == ["units", "revenue"]

    def test_a_time_column_wins_over_a_category(self):
        chart = infer_chart(
            ["region", "month", "units"],
            [["West", date(2026, 7, 1), 10], ["East", date(2026, 8, 1), 4]],
            truncated=False,
        )

        assert chart["type"] == "line" and chart["x"] == "month"

    def test_decimals_count_as_numbers(self):
        chart = infer_chart(
            ["region", "revenue"],
            [["West", Decimal("2500.50")], ["East", Decimal("1800.00")]],
            truncated=False,
        )

        assert chart["y"] == ["revenue"]


class TestWhenATableSaysItBetter:
    def test_a_single_row_is_a_number_not_a_chart(self):
        assert infer_chart(["region", "units"], [["West", 10]], truncated=False) is None

    def test_one_column_cannot_be_charted(self):
        assert infer_chart(["total"], [[10], [20]], truncated=False) is None

    def test_a_truncated_result_is_never_charted(self):
        """The picture would imply the whole answer while showing part of it."""
        rows = [["West", 10], ["East", 4]]

        assert infer_chart(["region", "units"], rows, truncated=True) is None

    def test_repeated_labels_mean_the_query_was_not_aggregated(self):
        rows = [["West", 10], ["West", 6], ["East", 4]]

        assert infer_chart(["region", "units"], rows, truncated=False) is None

    def test_a_result_with_no_numbers_has_nothing_to_plot(self):
        rows = [["West", "Cell"], ["East", "Pack"]]

        assert infer_chart(["region", "product"], rows, truncated=False) is None

    def test_a_result_with_no_labels_has_no_axis(self):
        assert infer_chart(["units", "revenue"], [[10, 250], [4, 180]], truncated=False) is None

    def test_too_many_points_is_noise(self):
        rows = [[f"r{i}", i] for i in range(MAX_POINTS + 1)]

        assert infer_chart(["region", "units"], rows, truncated=False) is None

    def test_at_the_limit_it_still_charts(self):
        rows = [[f"r{i}", i] for i in range(MAX_POINTS)]

        assert infer_chart(["region", "units"], rows, truncated=False) is not None

    def test_a_boolean_is_not_a_measure(self):
        rows = [["West", True], ["East", False]]

        assert infer_chart(["region", "active"], rows, truncated=False) is None


class TestNulls:
    def test_a_column_of_nulls_is_ignored_rather_than_misread(self):
        rows = [["West", None, 10], ["East", None, 4]]

        chart = infer_chart(["region", "makemodel", "units"], rows, truncated=False)

        assert chart == {"type": "bar", "x": "region", "y": ["units"]}

    @pytest.mark.parametrize("rows", [[], [[]]])
    def test_an_empty_result_is_not_a_chart(self, rows):
        assert infer_chart(["region", "units"], rows, truncated=False) is None


class TestForecastChart:
    def _payload(self, history: int, horizon: int) -> dict:
        return {
            "grain": "day",
            "interval": 0.8,
            "history": [[f"h{i}", float(i)] for i in range(history)],
            "points": [[f"p{i}", 1.0, 0.0, 2.0] for i in range(horizon)],
            "time_column": "day",
            "value_column": "units",
        }

    def test_it_names_the_axes_the_rows_used(self):
        chart = forecast_chart(self._payload(10, 3))

        assert (chart["type"], chart["x"], chart["y"]) == ("forecast", "day", ["units"])
        assert chart["forecast"]["points"] == self._payload(10, 3)["points"]

    def test_old_history_is_trimmed_so_the_picture_stays_readable(self):
        chart = forecast_chart(self._payload(250, 12))

        assert len(chart["forecast"]["history"]) == MAX_POINTS - 12
        assert chart["forecast"]["history"][-1] == ["h249", 249.0]

    def test_a_long_horizon_still_keeps_enough_history_to_read_it_against(self):
        chart = forecast_chart(self._payload(250, 199))

        assert len(chart["forecast"]["history"]) == 8
