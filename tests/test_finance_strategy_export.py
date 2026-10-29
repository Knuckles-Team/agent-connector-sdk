"""Strategy export: one spec rendered as Pine Script v6, MQL5 and TDX source."""

from __future__ import annotations

import pytest

from agent_connector_sdk.finance.strategy_export import (
    ExportPlatform,
    ExportResult,
    MQL5Exporter,
    PineScriptExporter,
    StrategyCondition,
    StrategyExporter,
    StrategySpec,
    TDXExporter,
)

SPEC = StrategySpec(
    name="RSI Momentum",
    entry_long=[
        StrategyCondition(indicator="rsi", operator="crosses_above", value=30),
        StrategyCondition(indicator="volume", operator=">", value=1000000),
    ],
    entry_short=[
        StrategyCondition(indicator="rsi", operator="crosses_below", value=70)
    ],
    exit_long=[StrategyCondition(indicator="rsi", operator=">", value=70)],
    stop_loss_pct=2.0,
    take_profit_pct=5.0,
)


@pytest.mark.parametrize(
    ("exporter", "filename", "fragments"),
    [
        (
            PineScriptExporter(),
            "rsi_momentum.pine",
            (
                "//@version=6",
                "strategy(",
                "ta.crossover",
                "strategy.entry",
                "strategy.exit",
                " and ",
            ),
        ),
        (
            MQL5Exporter(),
            ".mq5",
            (
                "void OnTick()",
                "OrderSend",
                "input double LotSize",
                "input double StopLoss",
            ),
        ),
        (TDXExporter(), ".tdx", ("买入信号",)),
    ],
)
def test_each_platform_renders_its_own_syntax(
    exporter: object, filename: str, fragments: tuple[str, ...]
) -> None:
    result = exporter.export(SPEC)  # type: ignore[attr-defined]
    assert isinstance(result, ExportResult)
    assert filename in result.filename
    for fragment in fragments:
        assert fragment in result.code


@pytest.mark.spec("SCION-FINANCE-SOURCES-R900.1")
def test_exporter_dispatches_by_platform_and_exports_all() -> None:
    exporter = StrategyExporter()
    assert set(exporter.supported_platforms) == {
        ExportPlatform.PINE_SCRIPT_V6,
        ExportPlatform.MQL5,
        ExportPlatform.TDX,
    }
    assert exporter.export(SPEC, ExportPlatform.MQL5).platform is ExportPlatform.MQL5
    assert {r.platform for r in exporter.export_all(SPEC)} == set(
        exporter.supported_platforms
    )
