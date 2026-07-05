"""FastMCP entry point for ``mcp-cbr-rates``.

Run as:

    python -m mcp_cbr_rates
    # or, after `pip install atomno-mcp-cbr-rates`:
    atomno-mcp-cbr-rates
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP

from . import __version__
from .cache import TTLCache
from .client import DEFAULT_TIMEOUT, CbrClient
from .errors import CbrError
from .schemas import (
    CurrencyRate,
    HistoryRates,
    InflationData,
    KeyRateHistory,
    MacroSnapshot,
)
from .tools import (
    DEFAULT_DAILY_TTL,
    DEFAULT_HISTORY_TTL,
    ToolContext,
)
from .tools import (
    get_rate as _get_rate,
)
from .tools import (
    history_rates as _history_rates,
)
from .tools import (
    inflation as _inflation,
)
from .tools import (
    key_rate as _key_rate,
)
from .tools import (
    statistics as _statistics,
)

logger = logging.getLogger("mcp_cbr_rates")


# ---------------------------------------------------------------------------
# Env-var compatibility layer.
#
# Project-wide convention is `MCP_<NAME>_<KEY>` (см. PRODUCTS/ATOMNO/_knowledge/
# MCP_BUILD_CHECKLIST.md). Старые имена `CBR_<KEY>` поддерживаются ради
# обратной совместимости и логируют DeprecationWarning один раз за процесс.
# Новые имена приоритетны: если оба заданы — выигрывает MCP_CBR_*.
# ---------------------------------------------------------------------------

_LEGACY_ENV_RENAME: dict[str, str] = {
    "CBR_LOG_LEVEL": "MCP_CBR_LOG_LEVEL",
    "CBR_HTTP_TIMEOUT": "MCP_CBR_HTTP_TIMEOUT",
    "CBR_CACHE_DAILY_TTL": "MCP_CBR_CACHE_DAILY_TTL",
    "CBR_CACHE_HISTORY_TTL": "MCP_CBR_CACHE_HISTORY_TTL",
}
_warned_legacy_envs: set[str] = set()


def _resolve_env(canonical_name: str) -> str | None:
    """Найти значение env-переменной с поддержкой старого имени.

    Приоритет: `MCP_CBR_*` (canonical) > `CBR_*` (legacy, с DeprecationWarning).
    """
    value = os.environ.get(canonical_name)
    if value:
        return value
    legacy_name = next(
        (legacy for legacy, canonical in _LEGACY_ENV_RENAME.items()
         if canonical == canonical_name),
        None,
    )
    if legacy_name is None:
        return None
    legacy_value = os.environ.get(legacy_name)
    if legacy_value and legacy_name not in _warned_legacy_envs:
        _warned_legacy_envs.add(legacy_name)
        logger.warning(
            "%s is deprecated since v0.1.2; use %s instead. "
            "Old name still works but will be removed in a future release.",
            legacy_name, canonical_name,
        )
    return legacy_value


def _read_float_env(name: str, default: float) -> float:
    raw = _resolve_env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid float in env var %s=%r, using %s", name, raw, default)
        return default


def build_tool_context() -> tuple[ToolContext, httpx.AsyncClient]:
    """Construct the ``ToolContext`` used by every tool, returning the owned HTTP client."""
    timeout = _read_float_env("MCP_CBR_HTTP_TIMEOUT", DEFAULT_TIMEOUT)
    daily_ttl = _read_float_env("MCP_CBR_CACHE_DAILY_TTL", DEFAULT_DAILY_TTL)
    history_ttl = _read_float_env("MCP_CBR_CACHE_HISTORY_TTL", DEFAULT_HISTORY_TTL)

    http_client = httpx.AsyncClient(
        timeout=timeout,
        headers={
            "User-Agent": f"mcp-cbr-rates/{__version__} (+https://github.com/atomno-mcp/mcp-cbr-rates)",
            "Accept": "application/xml,text/xml,*/*",
        },
        transport=httpx.AsyncHTTPTransport(retries=2),
    )
    cbr = CbrClient(http_client=http_client, timeout=timeout)
    daily_cache = TTLCache(default_ttl=daily_ttl)
    history_cache = TTLCache(default_ttl=history_ttl)
    return ToolContext(client=cbr, daily_cache=daily_cache, history_cache=history_cache), http_client


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[ToolContext]:
    ctx, http_client = build_tool_context()
    try:
        yield ctx
    finally:
        try:
            await ctx.client.aclose()
        finally:
            await http_client.aclose()


mcp = FastMCP(
    name="mcp-cbr-rates",
    instructions=(
        "Tools for the public Bank of Russia (CBR) data: currency quotes, key"
        " rate, inflation, and a compact macro snapshot. All data comes from"
        " cbr.ru and is cached briefly to be polite."
    ),
    lifespan=_lifespan,
)


def _ctx(ctx: Context) -> ToolContext:
    """Resolve the lifespan-provided ToolContext from the request context."""
    lifespan_ctx = ctx.request_context.lifespan_context
    if not isinstance(lifespan_ctx, ToolContext):  # pragma: no cover
        raise RuntimeError("server is not initialized: missing ToolContext")
    return lifespan_ctx


def _format_error(exc: Exception) -> str:
    name = type(exc).__name__
    return f"{name}: {exc}"


@mcp.tool(
    name="get_rate",
    description=(
        "Get the official Bank of Russia exchange rate for a single currency"
        " on a given date (or the latest published date if 'on_date' is omitted)."
        " Returns nominal, value, per-unit rate and effective quote date."
    ),
)
async def tool_get_rate(
    ctx: Context,
    char_code: str,
    on_date: date | None = None,
) -> CurrencyRate:
    try:
        return await _get_rate(_ctx(ctx), char_code=char_code, on_date=on_date)
    except CbrError as exc:
        raise RuntimeError(_format_error(exc)) from exc


@mcp.tool(
    name="history_rates",
    description=(
        "Get the official CBR exchange-rate series for a single currency between"
        " two dates inclusive. Range capped at 366 days; for longer windows call"
        " repeatedly."
    ),
)
async def tool_history_rates(
    ctx: Context,
    char_code: str,
    date_from: date,
    date_to: date,
) -> HistoryRates:
    try:
        return await _history_rates(
            _ctx(ctx), char_code=char_code, date_from=date_from, date_to=date_to
        )
    except CbrError as exc:
        raise RuntimeError(_format_error(exc)) from exc


@mcp.tool(
    name="key_rate",
    description=(
        "Get the CBR key-rate (ставка рефинансирования) time series for the"
        " requested range. Defaults to the most recent 30 days."
    ),
)
async def tool_key_rate(
    ctx: Context,
    date_from: date | None = None,
    date_to: date | None = None,
) -> KeyRateHistory:
    try:
        return await _key_rate(_ctx(ctx), date_from=date_from, date_to=date_to)
    except CbrError as exc:
        raise RuntimeError(_format_error(exc)) from exc


@mcp.tool(
    name="inflation",
    description=(
        "Get monthly year-over-year consumer price index (CPI) inflation as"
        " published by CBR for the given year range (defaults to the previous"
        " and current year)."
    ),
)
async def tool_inflation(
    ctx: Context,
    year_from: int | None = None,
    year_to: int | None = None,
) -> InflationData:
    try:
        return await _inflation(_ctx(ctx), year_from=year_from, year_to=year_to)
    except CbrError as exc:
        raise RuntimeError(_format_error(exc)) from exc


@mcp.tool(
    name="statistics",
    description=(
        "Get a compact macro snapshot: latest key rate, USD/EUR/CNY rates,"
        " latest YoY inflation, and the period the inflation refers to."
    ),
)
async def tool_statistics(ctx: Context) -> MacroSnapshot:
    try:
        return await _statistics(_ctx(ctx))
    except CbrError as exc:
        raise RuntimeError(_format_error(exc)) from exc


# ---------------------------------------------------------------------------
# CLI entry point — argparse-обвязка.
# ---------------------------------------------------------------------------

_SUPPORTED_TRANSPORTS = ("stdio", "http", "sse", "streamable-http")
_DEFAULT_TRANSPORT = "stdio"
_DEFAULT_HTTP_HOST = "127.0.0.1"
_DEFAULT_HTTP_PORT = 8000
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _build_arg_parser() -> argparse.ArgumentParser:
    """Create the argparse parser for the `atomno-mcp-cbr-rates` CLI."""
    parser = argparse.ArgumentParser(
        prog="atomno-mcp-cbr-rates",
        description=(
            "MCP-сервер для публичных данных Банка России (ЦБ РФ): курсы валют, "
            "ключевая ставка, инфляция, макроэкономический snapshot. Источник — cbr.ru."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"atomno-mcp-cbr-rates {__version__}",
    )
    parser.add_argument(
        "--transport", "-t",
        choices=_SUPPORTED_TRANSPORTS,
        default=_DEFAULT_TRANSPORT,
        help=(
            "MCP-транспорт. По умолчанию stdio (для Cursor / Claude Desktop / Cline). "
            "Сетевые транспорты используют --host / --port."
        ),
    )
    parser.add_argument(
        "--host",
        default=_DEFAULT_HTTP_HOST,
        help=(
            f"Host для http/sse/streamable-http транспортов "
            f"(по умолчанию {_DEFAULT_HTTP_HOST})."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_HTTP_PORT,
        help=(
            f"Port для http/sse/streamable-http транспортов "
            f"(по умолчанию {_DEFAULT_HTTP_PORT})."
        ),
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=_VALID_LOG_LEVELS,
        default=None,
        help=(
            "Уровень логирования. Приоритет над env-переменной MCP_CBR_LOG_LEVEL "
            "(а также legacy-именем CBR_LOG_LEVEL). "
            "По умолчанию используется значение из env или INFO."
        ),
    )
    return parser


def _resolve_log_level(cli_value: str | None) -> str:
    """Resolve the log level: CLI > env > INFO. Invalid env exits 2."""
    if cli_value is not None:
        return cli_value.upper()
    raw_env = _resolve_env("MCP_CBR_LOG_LEVEL")
    if raw_env is not None:
        normalized = raw_env.strip().upper()
        if normalized not in _VALID_LOG_LEVELS:
            print(
                f"mcp-cbr-rates: invalid MCP_CBR_LOG_LEVEL='{raw_env}' "
                f"(allowed: {', '.join(_VALID_LOG_LEVELS)})",
                file=sys.stderr,
            )
            raise SystemExit(2)
        return normalized
    return "INFO"


def main(argv: list[str] | None = None) -> int:
    """Run the FastMCP server with an argparse CLI.

    Args:
        argv: Optional list of CLI arguments (without ``argv[0]``). Defaults to ``sys.argv[1:]``.

    Returns:
        Exit-code: 0 on graceful exit, 2 on configuration error.
    """
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    log_level = _resolve_log_level(args.log_level)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    logger.info(
        "atomno-mcp-cbr-rates %s starting (transport=%s)",
        __version__,
        args.transport,
    )

    run_kwargs: dict[str, Any] = {"transport": args.transport}
    if args.transport in ("http", "sse", "streamable-http"):
        run_kwargs["host"] = args.host
        run_kwargs["port"] = args.port

    mcp.run(**run_kwargs)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
