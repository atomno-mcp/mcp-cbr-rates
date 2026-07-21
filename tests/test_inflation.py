"""Tests for ``tools.inflation``."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from mcp_cbr_rates.errors import CbrApiError, CbrParseError, CbrValidationError
from mcp_cbr_rates.tools import inflation

from .conftest import load_fixture


@pytest.mark.asyncio
async def test_inflation_happy_path_filters_by_year(tool_ctx) -> None:
    html = load_fixture("inflation.html")
    with respx.mock(base_url="https://www.cbr.ru") as router:
        router.get("/hd_base/infl/").mock(
            return_value=httpx.Response(200, content=html)
        )
        data = await inflation(tool_ctx, year_from=2026, year_to=2026)
    assert len(data.points) == 3
    assert {p.month for p in data.points} == {1, 2, 3}
    march = next(p for p in data.points if p.month == 3)
    assert march.cpi_yoy_pct == Decimal("10.34")


@pytest.mark.asyncio
async def test_inflation_accepts_current_numeric_month_format(tool_ctx) -> None:
    html = b"""
    <table class="data">
      <tr><th>Date</th><th>Key rate</th><th>Inflation</th><th>Target</th></tr>
      <tr><td>06.2026</td><td>14,25</td><td>6,02</td><td>4,00</td></tr>
      <tr><td>05.2026</td><td>14,50</td><td>5,31</td><td>4,00</td></tr>
    </table>
    """
    with respx.mock(base_url="https://www.cbr.ru") as router:
        router.get("/hd_base/infl/").mock(
            return_value=httpx.Response(200, content=html)
        )
        data = await inflation(tool_ctx, year_from=2026, year_to=2026)

    assert [(point.month, point.cpi_yoy_pct) for point in data.points] == [
        (5, Decimal("5.31")),
        (6, Decimal("6.02")),
    ]


@pytest.mark.asyncio
async def test_inflation_raises_when_table_format_is_unrecognized(tool_ctx) -> None:
    html = b'<table class="data"><tr><td>unexpected</td><td>1</td><td>2</td></tr></table>'
    with respx.mock(base_url="https://www.cbr.ru") as router:
        router.get("/hd_base/infl/").mock(
            return_value=httpx.Response(200, content=html)
        )
        with pytest.raises(CbrParseError, match="no recognizable monthly observations"):
            await inflation(tool_ctx, year_from=2026, year_to=2026)


@pytest.mark.asyncio
async def test_inflation_returns_full_range_when_unspecified(tool_ctx) -> None:
    html = load_fixture("inflation.html")
    with respx.mock(base_url="https://www.cbr.ru") as router:
        router.get("/hd_base/infl/").mock(
            return_value=httpx.Response(200, content=html)
        )
        data = await inflation(tool_ctx, year_from=2025, year_to=2026)
    assert len(data.points) == 6
    assert data.points[0].year == 2025
    assert data.points[-1].year == 2026


@pytest.mark.asyncio
async def test_inflation_inverted_years_raises_validation_error(tool_ctx) -> None:
    with pytest.raises(CbrValidationError):
        await inflation(tool_ctx, year_from=2026, year_to=2024)


@pytest.mark.asyncio
async def test_inflation_5xx_raises_api_error(tool_ctx) -> None:
    with respx.mock(base_url="https://www.cbr.ru") as router:
        router.get("/hd_base/infl/").mock(
            return_value=httpx.Response(500, content=b"err")
        )
        with pytest.raises(CbrApiError):
            await inflation(tool_ctx, year_from=2026, year_to=2026)


@pytest.mark.asyncio
async def test_inflation_caches_full_dataset(tool_ctx) -> None:
    html = load_fixture("inflation.html")
    with respx.mock(base_url="https://www.cbr.ru") as router:
        route = router.get("/hd_base/infl/").mock(
            return_value=httpx.Response(200, content=html)
        )
        await inflation(tool_ctx, year_from=2026, year_to=2026)
        await inflation(tool_ctx, year_from=2025, year_to=2025)
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_inflation_filters_out_years_outside_range(tool_ctx) -> None:
    html = load_fixture("inflation.html")
    with respx.mock(base_url="https://www.cbr.ru") as router:
        router.get("/hd_base/infl/").mock(
            return_value=httpx.Response(200, content=html)
        )
        data = await inflation(tool_ctx, year_from=2030, year_to=2031)
    assert data.points == []
