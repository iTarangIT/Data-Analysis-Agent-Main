"""A customer's connection string opens with psycopg however its scheme was written.

The form accepts `postgresql://`, which is what every host's console hands out, and SQLAlchemy
reads that as psycopg2, which is not installed. The failure surfaced as "could not connect to
that database with the details given", which reads like a wrong password.
"""

import pytest

from app.database_mcp import CustomerDatabase


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@h:5432/db?sslmode=require",
        "postgresql+psycopg://u:p@h:5432/db?sslmode=require",
    ],
)
def test_opens_with_psycopg(dsn):
    url = CustomerDatabase(dsn).engine.url

    assert url.render_as_string(hide_password=False) == (
        "postgresql+psycopg://u:p@h:5432/db?sslmode=require"
    )
