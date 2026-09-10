"""Suggesting a chart for a result that has one.

No model call. Section 16.2 put this in `answer_node`, which the create_agent refactor deleted,
but its trigger condition was already deterministic: chart when the rows are numeric-heavy.
What was lost was the emission site, not the decision.

Deciding here rather than asking the model keeps the whole result out of the model's context,
costs no tokens against a 20-request-per-day quota, and is the only version an offline eval can
assert.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

# Beyond this a bar chart is noise and a line chart is a smear.
MAX_POINTS = 200


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def _column(rows: list[list[Any]], index: int) -> list[Any]:
    return [row[index] for row in rows if row[index] is not None]


def infer_chart(columns: list[str], rows: list[list[Any]], truncated: bool) -> dict | None:
    """Return a chart spec for this result, or None when a table says it better.

    A truncated result is never charted: the picture would imply the whole answer while showing
    part of it, which is worse than no picture.
    """
    if truncated or len(rows) < 2 or len(columns) < 2 or len(rows) > MAX_POINTS:
        return None

    temporal, numeric, categorical = [], [], []
    for i, name in enumerate(columns):
        values = _column(rows, i)
        if not values:
            continue
        if all(isinstance(v, date | datetime) for v in values):
            temporal.append((i, name))
        elif all(_is_number(v) for v in values):
            numeric.append((i, name))
        else:
            categorical.append((i, name))

    axis = (temporal or categorical)[:1]
    if not axis or not numeric:
        return None

    index, x = axis[0]
    # Repeated labels mean the query was not aggregated, and a bar chart over them is simply
    # wrong. Cheap to check, and it rules out the commonest bad chart.
    labels = [row[index] for row in rows]
    if len(set(labels)) != len(labels):
        return None

    return {
        "type": "line" if temporal else "bar",
        "x": x,
        "y": [name for _, name in numeric],
    }
