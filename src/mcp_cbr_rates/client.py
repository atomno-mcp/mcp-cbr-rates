"""Async HTTP client wrapping the public Bank of Russia (CBR) endpoints.

CBR exposes data through three families of services:

* **XML scripts** (``XML_daily.asp``, ``XML_dynamic.asp``, ``XML_valFull.asp``)
  — return ``windows-1251``-encoded XML with comma-separated decimals.
* **DailyInfo SOAP service** at
  ``https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx`` — the only documented
  source for the key rate time series.
* **Public HTML page** ``https://www.cbr.ru/hd_base/infl/`` — the easiest
  programmatic source for monthly CPI (consumer price index) figures, since
  the SOAP service does not expose them.

This module isolates parsing and transport concerns. The tool layer in
``tools.py`` calls these methods, applies caching, and reshapes the data into
the response models defined in ``schemas.py``.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Final

import httpx
from defusedxml import ElementTree as ET  # noqa: N817 — `ET` is the canonical xml.etree alias

from .currency_codes import get_cbr_id, normalize_char_code
from .errors import (
    CbrApiError,
    CbrNotFoundError,
    CbrParseError,
    CbrTimeoutError,
)

logger = logging.getLogger(__name__)

CBR_BASE_URL: Final[str] = "https://www.cbr.ru"
SOAP_URL: Final[str] = f"{CBR_BASE_URL}/DailyInfoWebServ/DailyInfo.asmx"
INFLATION_URL: Final[str] = f"{CBR_BASE_URL}/hd_base/infl/"
DEFAULT_TIMEOUT: Final[float] = 15.0

_RU_MONTHS: Final[dict[str, int]] = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def _to_decimal(raw: str | None) -> Decimal:
    """Parse a CBR-format numeric string ('91,5421' or '91.5421') into Decimal."""
    if raw is None:
        raise CbrParseError("missing decimal value in CBR response")
    text = raw.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        raise CbrParseError("empty decimal value in CBR response")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise CbrParseError(f"cannot parse {raw!r} as decimal") from exc


def _to_decimal_optional(raw: str | None) -> Decimal | None:
    if raw is None or not raw.strip() or raw.strip() in {"-", "—", "n/a"}:
        return None
    try:
        return _to_decimal(raw)
    except CbrParseError:
        return None


def _to_date_ddmmyyyy(raw: str) -> date:
    """Parse CBR's ``DD.MM.YYYY`` date format."""
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except (ValueError, TypeError) as exc:
        raise CbrParseError(f"cannot parse {raw!r} as DD.MM.YYYY date") from exc


def _format_ddmmyyyy(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _parse_xml_bytes(payload: bytes) -> ET.Element:
    """Parse possibly windows-1251 encoded XML returned by CBR scripts."""
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:  # pragma: no cover - covered by integration tests
        raise CbrParseError(f"invalid XML from CBR: {exc}") from exc


class _InflationTableParser(HTMLParser):
    """Tolerant parser of the single ``<table class="data">`` on the CBR page.

    The expected row shape is:
    ``[empty | "Дата" | "Ключевая ставка..." | "Инфляция..." | "Цель..."]``
    (occasionally with extra leading empty cells).

    We accept any row with at least three textual cells where the first cell
    looks like a Russian "month YYYY" string.
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "table":
            classes = dict(attrs).get("class") or ""
            if "data" in classes.split():
                self._in_table = True
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._in_table = False
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._current_row:
                self.rows.append(self._current_row)
        elif tag in {"td", "th"} and self._in_cell:
            self._in_cell = False
            self._current_row.append("".join(self._current_cell).strip())

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def _parse_ru_month_year(raw: str) -> tuple[int, int] | None:
    """Parse CBR month labels such as ``март 2026`` or ``03.2026``."""
    if not raw:
        return None
    normalized = raw.lower().replace("\xa0", " ").strip()
    numeric_match = re.fullmatch(r"(0?[1-9]|1[0-2])\.(\d{4})", normalized)
    if numeric_match:
        return int(numeric_match.group(2)), int(numeric_match.group(1))

    parts = normalized.split()
    if len(parts) != 2:
        return None
    month_name, year_str = parts
    month = _RU_MONTHS.get(month_name)
    if not month:
        return None
    try:
        year = int(year_str)
    except ValueError:
        return None
    return year, month


class CbrClient:
    """Stateless wrapper around the CBR public endpoints.

    Lifecycle is bound to an injected ``httpx.AsyncClient`` so users (and tests)
    can fully control transports, mounts, retries and timeouts.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = "mcp-cbr-rates/0.1 (+https://github.com/atomno-mcp/mcp-cbr-rates)",
    ) -> None:
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/xml,text/xml,*/*"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> CbrClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _get(self, url: str, params: dict[str, str] | None = None) -> bytes:
        try:
            response = await self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise CbrTimeoutError(f"timeout while requesting {url}") from exc
        except httpx.HTTPError as exc:
            raise CbrApiError(f"transport error for {url}: {exc}") from exc

        if response.status_code == 404:
            raise CbrNotFoundError(f"resource not found at {url}")
        if response.status_code >= 400:
            raise CbrApiError(
                f"CBR returned HTTP {response.status_code} for {url}",
                status_code=response.status_code,
            )
        return response.content

    async def _post(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        try:
            response = await self._client.post(url, content=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise CbrTimeoutError(f"timeout while POSTing to {url}") from exc
        except httpx.HTTPError as exc:
            raise CbrApiError(f"transport error for {url}: {exc}") from exc

        if response.status_code >= 400:
            raise CbrApiError(
                f"CBR returned HTTP {response.status_code} for {url}",
                status_code=response.status_code,
            )
        return response.content

    async def fetch_daily_rates(self, on_date: date | None = None) -> dict[str, dict[str, str]]:
        """Return the full set of currency quotes for ``on_date`` (or latest)."""
        params = {"date_req": _format_ddmmyyyy(on_date)} if on_date else None
        payload = await self._get(f"{CBR_BASE_URL}/scripts/XML_daily.asp", params=params)
        root = _parse_xml_bytes(payload)
        result: dict[str, dict[str, str]] = {}
        published = root.attrib.get("Date")
        for valute in root.findall("Valute"):
            char_code_el = valute.find("CharCode")
            if char_code_el is None or not char_code_el.text:
                continue
            char_code = char_code_el.text.strip().upper()
            entry = {
                "id": valute.attrib.get("ID", ""),
                "num_code": (valute.findtext("NumCode") or "").strip(),
                "char_code": char_code,
                "name": (valute.findtext("Name") or "").strip(),
                "nominal": (valute.findtext("Nominal") or "1").strip(),
                "value": (valute.findtext("Value") or "").strip(),
                "vunit_rate": (valute.findtext("VunitRate") or "").strip(),
                "date": published or "",
            }
            result[char_code] = entry
        return result

    async def fetch_currency_rate(
        self, char_code: str, on_date: date | None = None
    ) -> dict[str, str]:
        """Return the quote dict for a single currency, raising if absent."""
        canonical = normalize_char_code(char_code)
        rates = await self.fetch_daily_rates(on_date)
        if canonical not in rates:
            raise CbrNotFoundError(
                f"currency {canonical!r} is not present in CBR daily rates"
                f" for {on_date.isoformat() if on_date else 'latest'}"
            )
        return rates[canonical]

    async def fetch_history(
        self, char_code: str, date_from: date, date_to: date
    ) -> tuple[str, list[dict[str, str]]]:
        """Return ``(name, points)`` for ``XML_dynamic.asp`` over ``[from, to]``."""
        canonical = normalize_char_code(char_code)
        cbr_id = get_cbr_id(canonical) or await self._lookup_cbr_id(canonical)
        if not cbr_id:
            raise CbrNotFoundError(f"unknown currency code {canonical!r}")
        params = {
            "date_req1": _format_ddmmyyyy(date_from),
            "date_req2": _format_ddmmyyyy(date_to),
            "VAL_NM_RQ": cbr_id,
        }
        payload = await self._get(f"{CBR_BASE_URL}/scripts/XML_dynamic.asp", params=params)
        root = _parse_xml_bytes(payload)
        points: list[dict[str, str]] = []
        for record in root.findall("Record"):
            points.append(
                {
                    "date": record.attrib.get("Date", ""),
                    "nominal": (record.findtext("Nominal") or "1").strip(),
                    "value": (record.findtext("Value") or "").strip(),
                    "vunit_rate": (record.findtext("VunitRate") or "").strip(),
                }
            )
        # Try to recover the human-readable name from the daily snapshot — it's
        # not present in the dynamic XML response.
        name = canonical
        return name, points

    async def _lookup_cbr_id(self, char_code: str) -> str | None:
        """Look up a CBR id via ``XML_valFull.asp`` for codes not in the static map."""
        payload = await self._get(f"{CBR_BASE_URL}/scripts/XML_valFull.asp", params={"d": "0"})
        root = _parse_xml_bytes(payload)
        for item in root.findall("Item"):
            iso = (item.findtext("ISO_Char_Code") or "").strip().upper()
            if iso == char_code:
                return item.attrib.get("ID")
        return None

    async def fetch_key_rate(
        self, date_from: date, date_to: date
    ) -> list[dict[str, str]]:
        """Return key-rate observations between ``date_from`` and ``date_to``."""
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            ' xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            "<soap:Body>"
            '<KeyRateXML xmlns="http://web.cbr.ru/">'
            f"<fromDate>{date_from.isoformat()}</fromDate>"
            f"<ToDate>{date_to.isoformat()}</ToDate>"
            "</KeyRateXML>"
            "</soap:Body>"
            "</soap:Envelope>"
        ).encode()
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://web.cbr.ru/KeyRateXML",
        }
        payload = await self._post(SOAP_URL, envelope, headers=headers)
        root = _parse_xml_bytes(payload)
        # Strip the SOAP envelope to find <KR> nodes anywhere underneath.
        results: list[dict[str, str]] = []
        for kr in root.iter():
            if kr.tag.split("}")[-1] != "KR":
                continue
            dt = ""
            rate = ""
            for child in kr:
                tag = child.tag.split("}")[-1]
                if tag == "DT":
                    dt = (child.text or "").strip()
                elif tag == "Rate":
                    rate = (child.text or "").strip()
            if dt and rate:
                results.append({"date": dt, "rate": rate})
        return results

    async def fetch_inflation_html(self) -> bytes:
        """Return the raw HTML of the public CBR inflation summary page."""
        return await self._get(INFLATION_URL)

    async def fetch_inflation(
        self,
    ) -> list[dict[str, str]]:
        """Return monthly inflation observations parsed from the public page.

        The CBR page lists year-over-year inflation in column 'Инфляция, %' for
        each month back to 2017. We do not attempt to filter — all the rows are
        returned so the caller can subset by year range.
        """
        html = await self.fetch_inflation_html()
        parser = _InflationTableParser()
        try:
            parser.feed(html.decode("utf-8", errors="replace"))
        except Exception as exc:  # pragma: no cover - parsing edge cases
            raise CbrParseError(f"failed to parse inflation HTML: {exc}") from exc

        results: list[dict[str, str]] = []
        for row in parser.rows:
            cells = [c for c in row if c]
            if len(cells) < 3:
                continue
            month_year = _parse_ru_month_year(cells[0])
            if month_year is None and len(cells) >= 4:
                month_year = _parse_ru_month_year(cells[1])
                value_idx = 3
            else:
                value_idx = 2
            if month_year is None:
                continue
            year, month = month_year
            inflation_text = cells[value_idx] if value_idx < len(cells) else ""
            inflation_text = re.sub(r"[^\d.,\-]", "", inflation_text)
            results.append(
                {
                    "year": str(year),
                    "month": str(month),
                    "cpi_yoy_pct": inflation_text,
                }
            )
        if not results:
            raise CbrParseError(
                "CBR inflation table contained no recognizable monthly observations"
            )
        return results
