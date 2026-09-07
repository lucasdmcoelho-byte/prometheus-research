import datetime as dt

import pytest

from prometheus.cvm_client import CVMFundamentalSnapshotBuilder, CVMStatementRow


def _row(statement, account, value, reference_date, period_start=None, scale="UNIDADE", exercise_order="ÚLTIMO"):
    return CVMStatementRow(
        cvm_code="25100",
        company_name="CURY",
        statement=statement,
        account_code=account,
        account_name=account,
        value=value,
        currency="BRL",
        scale=scale,
        reference_date=reference_date,
        period_start=period_start,
        received_at=dt.datetime.combine(reference_date + dt.timedelta(days=40), dt.time()),
        filing_type="ITR",
        source_url="https://dados.cvm.gov.br/documento",
        version="1",
        exercise_order=exercise_order,
    )


def test_cvm_snapshot_derives_auditable_fundamental_metrics():
    current = dt.date(2025, 6, 30)
    prior = dt.date(2024, 6, 30)
    rows = [
        _row("DRE", "3.01", 1_200, current, dt.date(2025, 1, 1)),
        _row("DRE", "3.11", 240, current, dt.date(2025, 1, 1)),
        _row("BPA", "1", 5_000, current),
        _row("BPP", "2.03", 2_000, current),
        _row("BPP", "2.01.04", 200, current),
        _row("BPP", "2.02.01", 400, current),
        _row("DRE", "3.01", 1_000, prior, dt.date(2024, 1, 1)),
        _row("DRE", "3.11", 200, prior, dt.date(2024, 1, 1)),
    ]

    snapshot = CVMFundamentalSnapshotBuilder().build(rows)
    metrics = snapshot["metrics"]

    assert snapshot["status"] == "AVAILABLE"
    assert metrics["revenue_growth"]["normalized"] == pytest.approx(0.20)
    assert metrics["earnings_growth"]["normalized"] == pytest.approx(0.20)
    assert metrics["profit_margin"]["normalized"] == pytest.approx(0.20)
    assert metrics["roe"]["normalized"] == pytest.approx(0.24)
    assert metrics["debt_to_equity"]["normalized"] == pytest.approx(0.30)
    assert metrics["revenue_growth"]["calculation"] == "(current revenue / prior comparable revenue) - 1"
    assert metrics["profit_margin"]["calculation"] == "net income / revenue"
    assert metrics["debt_to_equity"]["calculation"] == "gross debt / equity"
    assert snapshot["sources"][0]["source"] == "CVM"


def test_penultimate_comparative_column_is_never_selected_as_current():
    reference = dt.date(2026, 6, 30)
    rows = [
        _row("DRE", "3.01", 200, reference, dt.date(2026, 1, 1), exercise_order="ÚLTIMO"),
        _row("DRE", "3.01", 100, reference, dt.date(2025, 1, 1), exercise_order="PENÚLTIMO"),
        _row("DRE", "3.11", 40, reference, dt.date(2026, 1, 1), exercise_order="ÚLTIMO"),
        _row("DRE", "3.11", 10, reference, dt.date(2025, 1, 1), exercise_order="PENÚLTIMO"),
    ]
    metrics = CVMFundamentalSnapshotBuilder().build(rows)["metrics"]
    assert metrics["revenue"]["normalized"] == 200
    assert metrics["net_income"]["normalized"] == 40


def test_ttm_reconciles_current_ytd_prior_fy_and_prior_ytd():
    rows = []
    for account, current, annual, prior in [("3.01", 70, 100, 50), ("3.11", 14, 20, 10)]:
        rows.extend([
            _row("DRE", account, current, dt.date(2026, 6, 30), dt.date(2026, 1, 1)),
            _row("DRE", account, annual, dt.date(2025, 12, 31), dt.date(2025, 1, 1)),
            _row("DRE", account, prior, dt.date(2025, 6, 30), dt.date(2025, 1, 1)),
        ])
    ttm = CVMFundamentalSnapshotBuilder().build_ttm(rows)
    assert ttm["status"] == "PARTIAL"  # core TTM exists; optional flow metrics remain absent
    assert ttm["metrics"]["revenue"]["normalized"] == 120
    assert ttm["metrics"]["net_income"]["normalized"] == 24
    assert ttm["metrics"]["profit_margin"]["normalized"] == pytest.approx(0.2)
    assert ttm["metrics"]["profit_margin"]["calculation"] == "net_income / revenue"
    assert len(ttm["metrics"]["profit_margin"]["source_rows"]) == 6


def test_financial_history_preserves_per_metric_formula_and_raw_rows():
    reference = dt.date(2025, 12, 31)
    rows = [
        _row("DRE", "3.01", 100, reference, dt.date(2025, 1, 1)),
        _row("DRE", "3.11", 20, reference, dt.date(2025, 1, 1)),
        _row("BPP", "2.03", 80, reference),
    ]
    history = CVMFundamentalSnapshotBuilder().build_history(rows)
    metadata = history[0]["metric_metadata"]
    assert metadata["revenue"]["source_rows"][0].account_code == "3.01"
    assert metadata["profit_margin"]["calculation"] == "net income / revenue"


def test_ttm_accepts_comparative_column_only_for_its_actual_prior_period():
    rows = []
    for account, current, annual, comparative in [("3.01", 70, 100, 50), ("3.11", 14, 20, 10)]:
        rows.extend([
            _row("DRE", account, current, dt.date(2026, 3, 31), dt.date(2026, 1, 1), exercise_order="ÚLTIMO"),
            _row("DRE", account, annual, dt.date(2025, 12, 31), dt.date(2025, 1, 1), exercise_order="ÚLTIMO"),
            _row("DRE", account, comparative, dt.date(2025, 3, 31), dt.date(2025, 1, 1), exercise_order="PENÚLTIMO"),
        ])
    ttm = CVMFundamentalSnapshotBuilder().build_ttm(rows)
    assert ttm["metrics"]["revenue"]["normalized"] == 120
    assert ttm["metrics"]["net_income"]["normalized"] == 24


def test_current_column_wins_if_current_and_comparative_share_an_actual_period():
    reference = dt.date(2025, 3, 31)
    rows = [
        _row("DRE", "3.01", 60, reference, dt.date(2025, 1, 1), exercise_order="ÚLTIMO"),
        _row("DRE", "3.01", 50, reference, dt.date(2025, 1, 1), exercise_order="PENÚLTIMO"),
    ]
    metric = CVMFundamentalSnapshotBuilder().build(rows)["metrics"]["revenue"]
    assert metric["normalized"] == 60


def test_financial_institution_equity_layout_is_supported():
    reference = dt.date(2026, 6, 30)
    rows = [
        _row("DRE", "3.11", 20, reference, dt.date(2026,1,1)),
        _row("BPP", "2.03", 900, reference),
        _row("BPP", "2.08", 100, reference),
    ]
    rows[-2] = CVMStatementRow(**{**rows[-2].__dict__, "account_name": "Passivos Financeiros"})
    rows[-1] = CVMStatementRow(**{**rows[-1].__dict__, "account_name": "Patrimônio Líquido Consolidado"})
    metrics = CVMFundamentalSnapshotBuilder().build(rows)["metrics"]
    assert metrics["equity"]["normalized"] == 100


def test_financial_equity_is_selected_by_meaning_across_207_and_208_layouts():
    reference = dt.date(2026, 6, 30)
    for equity_code in ("2.07", "2.08"):
        rows = [
            CVMStatementRow(**{**_row("BPP", "2.03", 900, reference).__dict__, "account_name": "Provisões"}),
            CVMStatementRow(**{**_row("BPP", equity_code, 190, reference).__dict__, "account_name": "Patrimônio Líquido Consolidado"}),
        ]
        metric = CVMFundamentalSnapshotBuilder().build(rows)["metrics"]["equity"]
        assert metric["normalized"] == 190
        assert metric["source_rows"][0].account_code == equity_code


def test_parent_profit_precedes_consolidated_profit_for_shareholder_metrics():
    reference = dt.date(2026, 6, 30)
    rows = [
        _row("DRE", "3.11", 120, reference, dt.date(2026, 1, 1)),
        _row("DRE", "3.11.01", 100, reference, dt.date(2026, 1, 1)),
    ]
    metric = CVMFundamentalSnapshotBuilder().build(rows)["metrics"]["net_income"]
    assert metric["normalized"] == 100
    assert metric["source_rows"][0].account_code == "3.11.01"


def test_eps_is_not_multiplied_by_statement_monetary_scale():
    row = CVMStatementRow(**{
        **_row("DRE", "3.99.01.01", 2.14, dt.date(2026, 6, 30), dt.date(2026, 1, 1)).__dict__,
        "scale": "MIL",
    })
    assert row.normalized_value == 2.14


def test_financial_institution_net_income_layout_is_supported_for_snapshot_and_ttm():
    rows = []
    for reference, start, revenue, consolidated, parent in [
        (dt.date(2026, 6, 30), dt.date(2026, 1, 1), 70, 16, 14),
        (dt.date(2025, 12, 31), dt.date(2025, 1, 1), 100, 22, 20),
        (dt.date(2025, 6, 30), dt.date(2025, 1, 1), 50, 11, 10),
    ]:
        rows.extend([
            _row("DRE", "3.01", revenue, reference, start),
            CVMStatementRow(**{**_row("DRE", "3.09", consolidated, reference, start).__dict__, "account_name": "Lucro/Prejuízo Consolidado do Período"}),
            CVMStatementRow(**{**_row("DRE", "3.09.01", parent, reference, start).__dict__, "account_name": "Atribuído a Sócios da Empresa Controladora"}),
        ])

    snapshot = CVMFundamentalSnapshotBuilder().build(rows)
    ttm = CVMFundamentalSnapshotBuilder().build_ttm(rows)

    assert snapshot["metrics"]["net_income"]["normalized"] == 14
    assert snapshot["metrics"]["net_income"]["source_rows"][0].account_code == "3.09.01"
    assert ttm["metrics"]["net_income"]["normalized"] == 24
    assert {row.account_code for row in ttm["metrics"]["net_income"]["source_rows"]} == {"3.09.01"}


def test_pre_tax_account_309_is_not_misclassified_as_net_income():
    reference = dt.date(2026, 6, 30)
    row = CVMStatementRow(**{
        **_row("DRE", "3.09", 30, reference, dt.date(2026, 1, 1)).__dict__,
        "account_name": "Resultado Antes dos Tributos sobre o Lucro",
    })
    metric = CVMFundamentalSnapshotBuilder().build([row])["metrics"]["net_income"]
    assert metric["status"] == "MISSING"
    assert metric["normalized"] is None
