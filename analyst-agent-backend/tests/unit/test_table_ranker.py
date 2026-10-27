"""Which tables a whole-database run spells out for a question.

The fixture is shaped like a dealer CRM, because that is what the ranker has to get right in
practice: a person asking about leads, revenue or calls never names a table.
"""

import pytest

from app.agent.table_ranker import focus, rank, scores, tokens
from app.catalog.types import Catalog, CatalogTable, Column, Relationship, TableDef


def _t(name, columns, comment=None, rows=1000):
    return CatalogTable(
        definition=TableDef(
            name=name,
            comment=comment,
            columns=[Column(name=c, type="text") for c in columns],
        ),
        stats={"rows": "approx", "rows_approx": rows},
    )


TABLES = [
    _t(
        "dealer_leads",
        [
            "id",
            "dealer_name",
            "phone",
            "lead_status",
            "lead_source",
            "assigned_to",
            "interest_level",
            "lost_reason",
            "created_at",
            "city",
        ],
        "Sales leads for prospective dealers: one row per lead, with status and owner",
    ),
    _t(
        "dealer_lead_status_history",
        ["id", "lead_id", "from_status", "to_status", "changed_at"],
        "Every status change of a dealer lead",
    ),
    _t(
        "analyst_staff",
        ["user_id", "name", "role", "is_active"],
        "CRM staff (sales reps, managers): who a lead or account is assigned to",
    ),
    _t(
        "accounts",
        ["id", "dealer_id", "owner_id", "status", "created_at"],
        "Live dealer accounts after onboarding",
    ),
    _t("dealers", ["id", "business_name", "state", "city", "dealer_type"], "Onboarded dealers"),
    _t(
        "invoices",
        ["id", "dealer_id", "invoice_date", "total_amount", "status"],
        "Sales invoices issued to dealers",
    ),
    _t(
        "invoice_line_items",
        ["id", "invoice_id", "product_id", "qty", "amount", "invoice_date"],
        "Sales revenue by line: one row per product sold on an invoice; amount is GST-inclusive",
    ),
    _t(
        "ai_call_logs",
        ["id", "lead_id", "campaign_id", "outcome", "duration_s", "started_at"],
        "AI dialer calls to leads and their outcome",
    ),
    _t("bolna_calls", ["id", "execution_id", "status", "created_at"]),
    _t(
        "dialer_campaigns",
        ["id", "name", "status", "max_retries", "created_at"],
        "AI dialer calling campaigns",
    ),
    _t(
        "inventory",
        ["id", "product_id", "serial_number", "status", "warehouse"],
        "Battery and charger stock units",
    ),
    _t("products", ["id", "name", "category", "price"], "Product catalogue"),
    _t(
        "buyback_requests",
        ["id", "dealer_id", "status", "quoted_amount", "created_at"],
        "Battery buyback requests from dealers",
    ),
    _t(
        "expense_submissions",
        ["id", "submitted_by", "amount", "category", "status", "spent_on"],
        "Staff expense claims",
    ),
    _t(
        "sales_targets",
        ["id", "user_id", "month", "target_amount"],
        "Monthly sales targets per rep",
    ),
    _t(
        "telemetry_daily_summary",
        ["device_id", "day", "max_cell_temp", "soc_avg"],
        "Daily battery telemetry rollup per device",
        rows=500000,
    ),
    _t("module_usage_daily", ["user_id", "module", "day", "events"], "CRM page usage"),
]

RELATIONSHIPS = [
    Relationship(
        from_table="dealer_leads",
        from_columns=["assigned_to"],
        to_table="analyst_staff",
        to_columns=["user_id"],
        origin="inferred",
        cardinality="many_to_one",
    ),
    Relationship(
        from_table="invoice_line_items",
        from_columns=["invoice_id"],
        to_table="invoices",
        to_columns=["id"],
        origin="declared",
        cardinality="many_to_one",
    ),
    Relationship(
        from_table="invoices",
        from_columns=["dealer_id"],
        to_table="dealers",
        to_columns=["id"],
        origin="declared",
        cardinality="many_to_one",
    ),
    Relationship(
        from_table="ai_call_logs",
        from_columns=["campaign_id"],
        to_table="dialer_campaigns",
        to_columns=["id"],
        origin="declared",
        cardinality="many_to_one",
    ),
]

CATALOG = Catalog(tables=TABLES, relationships=RELATIONSHIPS)

# (question, a table the top 8 must hold)
QUESTIONS = [
    ("How many leads were created this month, by status?", "dealer_leads"),
    ("Show the monthly trend of converted leads this year", "dealer_leads"),
    ("Which salesperson has the most leads assigned?", "analyst_staff"),
    ("Which salesperson has the most leads assigned?", "dealer_leads"),
    ("What was our revenue last month?", "invoice_line_items"),
    ("Top 10 dealers by revenue this quarter", "dealers"),
    ("Top 10 dealers by revenue this quarter", "invoice_line_items"),
    ("How many calls did the AI dialer make yesterday and what were the outcomes?", "ai_call_logs"),
    ("Which campaign had the best connect rate?", "dialer_campaigns"),
    ("How much stock do we have of each product?", "inventory"),
    ("How many buyback requests are pending?", "buyback_requests"),
    ("Total expenses submitted by the team in September", "expense_submissions"),
    ("Are we on track against the sales target this month?", "sales_targets"),
    ("Why were leads lost last month?", "dealer_leads"),
    ("How many new dealer accounts went live?", "accounts"),
    ("What is the average battery temperature per device?", "telemetry_daily_summary"),
]


@pytest.mark.parametrize(("question", "expected"), QUESTIONS)
def test_the_table_a_question_needs_is_in_the_top_eight(question, expected):
    assert expected in rank(CATALOG, question, 8)


def test_the_best_match_comes_first():
    assert rank(CATALOG, "How many leads were created this month by status?", 8)[0] == (
        "dealer_leads"
    )


def test_a_join_partner_rides_along_with_a_top_table():
    picked = rank(CATALOG, "revenue by invoice line", 4)
    assert "invoice_line_items" in picked
    assert "invoices" in picked


def test_a_follow_up_keeps_the_tables_of_the_question_before_it():
    picked = rank(CATALOG, "and split that by city?", 8, prior=["How many leads came in?"])
    assert "dealer_leads" in picked


def test_a_question_matching_nothing_gets_the_largest_tables():
    assert rank(CATALOG, "give me an overview", 2)[0] == "telemetry_daily_summary"


def test_never_more_than_k():
    assert len(rank(CATALOG, "leads calls invoices stock buyback expenses targets", 5)) == 5


def test_scores_are_zero_for_unrelated_tables():
    s = scores(CATALOG, "buyback")
    assert s["buyback_requests"] > 0
    assert s["module_usage_daily"] == 0


def test_tokens_split_names_and_fold_plurals():
    assert tokens("dealer_leads") == ["dealer", "lead"]
    assert tokens("invoiceLineItems") == ["invoice", "line", "item"]
    assert tokens("status") == ["status"]
    assert tokens("categories") == ["category"]


class TestFocus:
    def test_a_small_catalog_is_left_whole(self):
        small = Catalog(tables=TABLES[:5])
        assert focus(small, "leads", k=8, limit=12).focus is None

    def test_a_large_catalog_gets_a_focus_and_keeps_every_table(self):
        focused = focus(CATALOG, "leads by status", k=4, limit=12)
        assert focused.focus is not None and len(focused.focus) == 4
        assert focused.table_names == CATALOG.table_names
