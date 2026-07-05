<!-- mcp-name: io.github.atomno-mcp/mcp-cbr-rates -->

# mcp-cbr-rates

> A Model Context Protocol (MCP) server that exposes public Bank of Russia
> (Центральный банк РФ, **CBR**) data — currency quotes, key rate, inflation
> and a compact macro snapshot — to AI agents.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/atomno-mcp-cbr-rates.svg)](https://pypi.org/project/atomno-mcp-cbr-rates/)
[![GitHub release](https://img.shields.io/github/v/release/atomno-mcp/mcp-cbr-rates.svg)](https://github.com/atomno-mcp/mcp-cbr-rates/releases)
[![Tests](https://img.shields.io/badge/tests-52%20passed-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-84%25-brightgreen.svg)](tests/)
![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![MCP](https://img.shields.io/badge/MCP-compatible-brightgreen.svg)
[![Glama](https://img.shields.io/badge/Glama-listed-7c3aed.svg)](https://glama.ai/mcp/servers/atomno-mcp/mcp-cbr-rates)

<a href="https://glama.ai/mcp/servers/atomno-mcp/mcp-cbr-rates">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/atomno-mcp/mcp-cbr-rates/badge" alt="mcp-cbr-rates MCP server" />
</a>

`mcp-cbr-rates` is part of the [atomno](https://atomno-mcp.ru) family of MCP
servers focused on the Russian fintech ecosystem. It is fully open-source,
requires no API keys, and is built on top of the official public CBR
endpoints.

---

## Features

- Five high-quality MCP tools, each with a strict Pydantic schema:
  `get_rate`, `history_rates`, `key_rate`, `inflation`, `statistics`.
- Built-in TTL (Time-To-Live) cache: 1 hour for daily quotes, 24 hours for
  historical series, to be polite to the source.
- Async ``httpx`` transport with automatic retries on 5xx errors.
- Safe XML parsing via ``defusedxml``.
- 50+ unit tests with ``respx``-mocked HTTP, ≥80 % coverage.
- No secrets, no telemetry, no third-party trackers.

---

## Quick start

### Install from PyPI (recommended)

```bash
pipx install atomno-mcp-cbr-rates
atomno-mcp-cbr-rates  # starts the MCP server over stdio
```

Or with `uv`:

```bash
uv tool install atomno-mcp-cbr-rates
```

### Install from source

```bash
git clone https://github.com/atomno-mcp/mcp-cbr-rates.git
cd mcp-cbr-rates
pip install -e .
atomno-mcp-cbr-rates  # starts the MCP server over stdio
```

### Use with Cursor

Add the following to `.cursor/mcp.json` (or your global `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "cbr-rates": {
      "command": "atomno-mcp-cbr-rates"
    }
  }
}
```

### Use with Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cbr-rates": {
      "command": "atomno-mcp-cbr-rates"
    }
  }
}
```

On Windows the config lives at
`%APPDATA%\Claude\claude_desktop_config.json`; on macOS at
`~/Library/Application Support/Claude/claude_desktop_config.json`.

### Use with Claude Code

```bash
claude mcp add cbr-rates -- atomno-mcp-cbr-rates
```

---

## Tools

| Name | Inputs | Returns |
|---|---|---|
| `get_rate` | `char_code: str`, `on_date?: date` | `CurrencyRate` — single quote on the given (or latest) date |
| `history_rates` | `char_code: str`, `date_from: date`, `date_to: date` | `HistoryRates` — series of daily quotes |
| `key_rate` | `date_from?: date`, `date_to?: date` | `KeyRateHistory` — CBR key-rate series |
| `inflation` | `year_from?: int`, `year_to?: int` | `InflationData` — monthly year-over-year CPI in percent |
| `statistics` | _(none)_ | `MacroSnapshot` — combined dashboard: key rate + USD/EUR/CNY + inflation |

Examples in plain English:

> *"What was the official EUR rate on April 25, 2024?"*
> Tool: `get_rate(char_code="EUR", on_date="2024-04-25")`

> *"Plot the daily USD-RUB rate over the last 90 days."*
> Tool: `history_rates(char_code="USD", date_from=..., date_to=...)`

> *"Give me the latest key rate, USD/EUR/CNY, and inflation in one go."*
> Tool: `statistics()`

The `history_rates` window is capped at 366 days; for longer periods, call
the tool repeatedly.

---

## Configuration

All settings are optional and read from environment variables:

| Variable | Default | Description |
|---|---|---|
| `MCP_CBR_HTTP_TIMEOUT` | `15` | HTTP timeout in seconds for CBR calls. |
| `MCP_CBR_CACHE_DAILY_TTL` | `3600` | Cache TTL for daily quotes (seconds). |
| `MCP_CBR_CACHE_HISTORY_TTL` | `86400` | Cache TTL for historical series and SOAP responses. |
| `MCP_CBR_LOG_LEVEL` | `INFO` | Standard Python log level. |

Legacy `CBR_*` names are still accepted for compatibility, but new configs should use `MCP_CBR_*`.

There are no API keys to configure — all CBR endpoints used here are public.

---

## Development

```bash
git clone https://github.com/atomno-mcp/mcp-cbr-rates.git
cd mcp-cbr-rates
python -m venv .venv && source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest --cov=src/mcp_cbr_rates
```

Layout:

```
apps/mcp-cbr-rates/
├── src/mcp_cbr_rates/
│   ├── server.py        # FastMCP entry point, tool registration
│   ├── tools.py         # high-level async tools with caching
│   ├── client.py        # httpx wrapper around CBR XML / SOAP / HTML endpoints
│   ├── schemas.py       # Pydantic v2 models for inputs & outputs
│   ├── cache.py         # async TTL cache
│   ├── currency_codes.py # static ISO → CBR id map (with dynamic fallback)
│   └── errors.py        # typed exception hierarchy
└── tests/               # respx-mocked unit tests + fixtures
```

---

## Data sources

* `https://www.cbr.ru/scripts/XML_daily.asp` — daily currency quotes.
* `https://www.cbr.ru/scripts/XML_dynamic.asp` — historical currency series.
* `https://www.cbr.ru/scripts/XML_valFull.asp` — currency code lookup.
* `https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx` — SOAP service for the
  CBR key rate.
* `https://www.cbr.ru/hd_base/infl/` — monthly year-over-year inflation table.

All endpoints are read-only and free of charge.

---

## Disclaimer

This project is **not affiliated with the Bank of Russia** in any way. It is
an unofficial, best-effort wrapper around publicly available data. Use at your
own risk; the authors disclaim any responsibility for the freshness, accuracy
or applicability of the data delivered through this server.

If CBR's HTML or XML schemas change, individual tools may stop working until
this package is updated. Please open an issue if you notice a regression.

---

## License

MIT — see [LICENSE](LICENSE).
