# Changelog

All notable changes to `atomno-mcp-cbr-rates` are documented here.

Записи ведутся на русском, заголовки — английские (Keep a Changelog).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.11] — 2026-09-04

### Fixed

- Разбор таблицы инфляции ЦБ понимает оба формата месяца: русские названия и `MM.YYYY` (`07.2026`). Если в таблице нет ни одной узнаваемой строки, возвращается ошибка разбора.

## [0.1.6] — 2026-07-06

### Changed

- Обновлены метаданные пакета PyPI: автор и контактный email переведены на бренд `atomno-mcp` (`hello@atomno-mcp.ru`).

## [0.1.5] — 2026-07-05

### Changed

- GitHub-организация переименована `atomno-labs` → `atomno-mcp`; обновлены ссылки на репозиторий и MCP-реестр (`pyproject.toml`, `server.json`, `README`, workflow публикации).

## [0.1.3] — 2026-05-14

### Fixed

- **Glama analyzer build**: restored the legacy `mcp-cbr-rates` console-script
  alias so existing Glama build specs and older user configs do not fail with
  `Failed to spawn: mcp-cbr-rates` after the 0.1.2 CLI rename.
- **Dockerfile**: container entrypoint now uses canonical `atomno-mcp-cbr-rates`
  and still ships the legacy `mcp-cbr-rates` binary alias.
- **Docs/config examples**: README and `.env.example` now use canonical
  `atomno-mcp-cbr-rates` and `MCP_CBR_*` names.

## [0.1.2] — 2026-04-26

Sync-патч с эталоном `atomno-mcp-fns-check 0.1.1`. Релиз приводит CLI-обвязку,
ограничения зависимостей и метаданные `pyproject.toml` к общим конвенциям
портфеля `atomno-mcp-*` (см. `PRODUCTS/ATOMNO/_knowledge/MCP_BUILD_CHECKLIST.md`).

### Fixed

- **CLI: `--help` и `--version` больше не вешают процесс.** До 0.1.2 запуск
  `mcp-cbr-rates --help` запускал FastMCP по stdio и подвисал, ожидая stdin.
  Теперь `main()` использует `argparse` и завершается с exit-code 0 без
  запуска сервера.
- **Loud-fail на невалидный `MCP_CBR_LOG_LEVEL`** — exit-code 2 + явное
  сообщение в stderr; больше нет silent-INFO-fallback.
- **Рассинхрон версии**: до 0.1.2 в `__init__.__version__` был `"0.1.0"`,
  в `pyproject.toml` — `"0.1.1"`. Теперь оба `0.1.2`.

### Added

- **Новые CLI-флаги**:
  - `--version` / `-V` — версия пакета;
  - `--transport {stdio,http,sse,streamable-http}` — выбор транспорта (default `stdio`);
  - `--host`, `--port` — для http/sse/streamable-http транспортов;
  - `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}` — приоритет над env.
- **`tests/test_cli.py`** — 25 тестов на CLI-обвязку и backward-compat env.
- **PEP 561 маркер `py.typed`** — type-аннотации видны mypy/IDE.
- **Дополнительные classifiers**: `Natural Language :: Russian`, `Typing :: Typed`,
  `Intended Audience :: Financial and Insurance Industry`, `Operating System :: OS Independent`,
  `Topic :: Software Development :: Libraries :: Python Modules`.

### Changed

- **BREAKING**: Console-script переименован: `mcp-cbr-rates` → **`atomno-mcp-cbr-rates`**.
  Унификация с PyPI-именем и `atomno-mcp-fns-check` / `atomno-mcp-egrul`.
  В конфигах Cursor / Claude Desktop / Cline нужно обновить `command`.
- **BREAKING (с backward-compat)**: Env-переменные переименованы под
  префикс `MCP_CBR_*` для конвенциональной унификации с другими
  серверами портфеля:

  | Было (deprecated) | Стало (canonical) |
  |---|---|
  | `CBR_LOG_LEVEL` | `MCP_CBR_LOG_LEVEL` |
  | `CBR_HTTP_TIMEOUT` | `MCP_CBR_HTTP_TIMEOUT` |
  | `CBR_CACHE_DAILY_TTL` | `MCP_CBR_CACHE_DAILY_TTL` |
  | `CBR_CACHE_HISTORY_TTL` | `MCP_CBR_CACHE_HISTORY_TTL` |

  Старые имена продолжают работать, но при первом обращении логируют
  `DeprecationWarning` (один раз за процесс). Удалятся в `0.2.0`.
- **Development Status**: `3 - Alpha` → `4 - Beta`.
- **`main(argv: list[str] | None = None) -> int`** — testable signature.
  При вызове через `python -m mcp_cbr_rates` теперь `raise SystemExit(main())`.
- **Dependency MAJOR-lock** — каждая зависимость теперь имеет верхнюю границу
  по SemVer:

  | Было | Стало |
  |---|---|
  | `mcp>=1.2.0` | `mcp>=1.2.0,<2.0.0` |
  | `httpx>=0.27.0` | `httpx>=0.27.0,<1.0.0` |
  | `pydantic>=2.6.0` | `pydantic>=2.6.0,<3.0.0` |
  | `defusedxml>=0.7.1` | `defusedxml>=0.7.1,<1.0.0` |

### Migration guide (0.1.1 → 0.1.2)

1. **Cursor / Claude Desktop / Cline config**: замените `"command": "mcp-cbr-rates"`
   на `"command": "atomno-mcp-cbr-rates"`.
2. **Env-переменные**: при возможности переименуйте `CBR_*` → `MCP_CBR_*`.
   Старые имена работают, но логируют DeprecationWarning. Полное удаление —
   в `0.2.0`.
3. **Через `uvx`**: `uvx atomno-mcp-cbr-rates` (без установки) — рекомендуется.

### Quality

- 77 тестов проходят, lint clean (ruff `E F W I N UP B ASYNC`).
- `twine check` PASSED.
- Smoke-test в чистом venv: `pip install dist/*.whl` →
  `atomno-mcp-cbr-rates --version` → OK.

## [0.1.1] — 2026-04-26

### Changed

- PyPI distribution rename: `mcp-cbr-rates` → `atomno-mcp-cbr-rates`
  (brand-consistent with `atomno-mcp-fns-check`).
- Расширен раздел `[project.urls]`: Documentation, Changelog, MCP Catalog (Glama).

### Added

- README: pipx / uv install instructions, PyPI badge, Glama.ai listing badge.
- `glama.json` для ownership claim под `atomno-labs`.
- Dockerfile для Glama.ai analyzer / self-hosting.

## [0.1.0] — 2026-04-25

### Added

- Initial MVP release.
- Five MCP tools: `get_rate`, `history_rates`, `key_rate`, `inflation`, `statistics`.
- `CbrClient` wrapping CBR XML scripts and SOAP web service via `httpx.AsyncClient`.
- In-memory async TTL cache (1h for daily lookups, 24h for historical series).
- Pydantic v2 schemas for every tool input and output.
- `respx`-based unit tests with recorded XML fixtures, coverage ≥ 80 %.
- MIT license, README with quickstart for Cursor / Claude Desktop / Claude Code.
