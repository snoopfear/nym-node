#!/usr/bin/env python3
"""
Nym node performance Telegram monitor.

Checks Nym Validator API every CHECK_INTERVAL_MINUTES and sends Telegram alerts
when the latest performance is below PERFORMANCE_THRESHOLD. Also sends mandatory
status reports at configured local times, e.g. 10:00 and 22:00 Europe/Moscow.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("nym-performance-bot")

PERFORMANCE_KEYS = {
    "performance",
    "score",
    "routing_score",
    "routing_score_percent",
    "mixnet_performance",
    "last_24h_performance",
    "performance_score",
    "average_performance",
    "avg_performance",
    "node_performance",
}

TIMESTAMP_KEYS = (
    "timestamp",
    "time",
    "datetime",
    "date_time",
    "created_at",
    "updated_at",
    "last_updated",
    "last_polled",
    "date",
    "day",
)

_LIST_KEYS_IN_PRIORITY = (
    "data",
    "history",
    "performance_history",
    "items",
    "results",
    "records",
)

_STOP = False


def _handle_stop(signum: int, frame: Any) -> None:  # noqa: ARG001
    global _STOP
    _STOP = True
    log.info("Received signal %s, stopping...", signum)


signal.signal(signal.SIGTERM, _handle_stop)
signal.signal(signal.SIGINT, _handle_stop)


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    node_id: str
    api_base_url: str
    check_interval_minutes: float
    performance_threshold: float
    report_times: tuple[str, ...]
    timezone_name: str
    http_timeout_seconds: float
    api_retry_attempts: int
    api_retry_delay_seconds: float
    api_retry_backoff: float
    alert_cooldown_minutes: float
    run_check_on_startup: bool
    loop_sleep_seconds: float

    @property
    def api_url(self) -> str:
        base = self.api_base_url.rstrip("/")
        return f"{base}/nym-nodes/performance-history/{self.node_id}"

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


def _get_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid float env var {name}={raw!r}") from exc


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid integer env var {name}={raw!r}") from exc
    if value < 1:
        raise SystemExit(f"Invalid integer env var {name}={raw!r}; expected >= 1")
    return value


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config() -> Config:
    report_times_raw = os.getenv("DAILY_REPORT_TIMES", "10:00,22:00")
    report_times = tuple(t.strip() for t in report_times_raw.split(",") if t.strip())
    for t in report_times:
        if not re.fullmatch(r"\d{2}:\d{2}", t):
            raise SystemExit(f"Invalid report time {t!r}; expected HH:MM, e.g. 10:00")

    return Config(
        telegram_bot_token=_get_required("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get_required("TELEGRAM_CHAT_ID"),
        node_id=_get_required("NYM_NODE_ID"),
        api_base_url=os.getenv("NYM_API_BASE_URL", "https://validator.nymtech.net/api/v1").strip(),
        check_interval_minutes=_get_float("CHECK_INTERVAL_MINUTES", 30.0),
        performance_threshold=_get_float("PERFORMANCE_THRESHOLD", 0.9),
        report_times=report_times,
        timezone_name=os.getenv("TIMEZONE", "Europe/Moscow").strip(),
        http_timeout_seconds=_get_float("HTTP_TIMEOUT_SECONDS", 15.0),
        api_retry_attempts=_get_int("API_RETRY_ATTEMPTS", 3),
        api_retry_delay_seconds=_get_float("API_RETRY_DELAY_SECONDS", 10.0),
        api_retry_backoff=_get_float("API_RETRY_BACKOFF", 1.5),
        alert_cooldown_minutes=_get_float("ALERT_COOLDOWN_MINUTES", 30.0),
        run_check_on_startup=_get_bool("RUN_CHECK_ON_STARTUP", True),
        loop_sleep_seconds=_get_float("LOOP_SLEEP_SECONDS", 20.0),
    )


def parse_number(value: Any) -> float | None:
    """Parse performance value and normalize it to 0..1 if needed."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        is_percent = text.endswith("%")
        text = text.rstrip("%").strip()
        try:
            number = float(text)
        except ValueError:
            return None
        if is_percent:
            number /= 100.0
    else:
        return None

    # API variants sometimes return 0.97, sometimes 97.0. Treat 1..100 as percent.
    if 1.0 < number <= 100.0:
        number /= 100.0
    if number < 0:
        return None
    return number


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Accept seconds or milliseconds since epoch.
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Allow plain dates.
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def timestamp_score(item: Any) -> datetime | None:
    if not isinstance(item, dict):
        return None
    for key in TIMESTAMP_KEYS:
        if key in item:
            dt = parse_datetime(item[key])
            if dt is not None:
                return dt
    return None


def find_performance_in_dict(obj: dict[str, Any]) -> tuple[float, str] | None:
    # Prefer explicit likely keys.
    for key, value in obj.items():
        key_lower = str(key).lower()
        if key_lower in PERFORMANCE_KEYS or (
            "performance" in key_lower and not isinstance(value, (dict, list))
        ):
            number = parse_number(value)
            if number is not None:
                return number, key

    # Then search one level deeper to support {"data": {"performance": ...}}.
    for key, value in obj.items():
        if isinstance(value, dict):
            found = find_performance_in_dict(value)
            if found:
                number, inner_key = found
                return number, f"{key}.{inner_key}"
    return None


def choose_latest_from_list(items: list[Any]) -> Any | None:
    if not items:
        return None
    dated_items = [(timestamp_score(item), idx, item) for idx, item in enumerate(items)]
    dated_items = [(dt, idx, item) for dt, idx, item in dated_items if dt is not None]
    if dated_items:
        return max(dated_items, key=lambda x: (x[0], x[1]))[2]
    return items[-1]


def iter_lists(obj: Any) -> Iterable[list[Any]]:
    if isinstance(obj, list):
        yield obj
    elif isinstance(obj, dict):
        for key in _LIST_KEYS_IN_PRIORITY:
            value = obj.get(key)
            if isinstance(value, list):
                yield value
        for value in obj.values():
            if isinstance(value, (dict, list)):
                yield from iter_lists(value)


def extract_latest_performance(payload: Any) -> tuple[float, dict[str, Any] | Any, str]:
    """
    Return normalized performance 0..1, source entry, and source key.

    The Nym endpoint is expected to return JSON, but deployments can wrap data
    differently. This function intentionally handles common wrappers:
    {data: [...]}, {data: {history: [...]}}, direct list, or direct object.
    """
    # First try: likely history lists; use newest/last entry.
    for items in iter_lists(payload):
        latest = choose_latest_from_list(items)
        if isinstance(latest, dict):
            found = find_performance_in_dict(latest)
            if found:
                performance, source_key = found
                return performance, latest, source_key
        else:
            performance = parse_number(latest)
            if performance is not None:
                return performance, latest, "list_value"

    # Second try: direct object with performance field.
    if isinstance(payload, dict):
        found = find_performance_in_dict(payload)
        if found:
            performance, source_key = found
            return performance, payload, source_key

    raise ValueError("Could not find a performance value in API response")


def fmt_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def extract_entry_time(entry: Any, tz: ZoneInfo) -> str | None:
    dt = timestamp_score(entry)
    if dt is None:
        return None
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


class FetchPerformanceError(RuntimeError):
    """Raised when all API fetch attempts failed."""

    def __init__(self, attempts: int, last_error: BaseException) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Failed to fetch performance after {attempts} attempt(s): {last_error}")


def fetch_performance_once(config: Config) -> tuple[float, Any, str]:
    response = requests.get(
        config.api_url,
        headers={"accept": "application/json", "user-agent": "nym-performance-bot/1.0"},
        timeout=config.http_timeout_seconds,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ValueError(f"API returned non-JSON response: {response.text[:300]!r}") from exc
    return extract_latest_performance(payload)


def fetch_performance(config: Config) -> tuple[float, Any, str]:
    """Fetch performance with configurable retries before giving up."""
    attempts = max(1, config.api_retry_attempts)
    delay = max(0.0, config.api_retry_delay_seconds)
    backoff = max(1.0, config.api_retry_backoff)
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return fetch_performance_once(config)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= attempts or _STOP:
                break
            log.warning(
                "API fetch attempt %s/%s failed: %s. Retrying in %.1fs",
                attempt,
                attempts,
                exc,
                delay,
            )
            if delay > 0:
                time.sleep(delay)
            delay *= backoff

    assert last_error is not None
    raise FetchPerformanceError(attempts, last_error) from last_error


def send_telegram(config: Config, text: str) -> None:
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": config.telegram_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=config.http_timeout_seconds,
    )
    response.raise_for_status()


def build_api_failure_message(config: Config, exc: BaseException, kind: str) -> str:
    now = datetime.now(config.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")
    attempts = exc.attempts if isinstance(exc, FetchPerformanceError) else config.api_retry_attempts
    last_error = exc.last_error if isinstance(exc, FetchPerformanceError) else exc
    return "\n".join(
        [
            kind,
            f"Node ID: {config.node_id}",
            f"API URL: {config.api_url}",
            f"Attempts: {attempts}",
            f"Checked at: {now}",
            f"Error: {html.unescape(str(last_error))[:1000]}",
        ]
    )


def build_status_message(
    config: Config,
    performance: float,
    entry: Any,
    source_key: str,
    kind: str,
) -> str:
    now = datetime.now(config.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")
    measured_at = extract_entry_time(entry, config.timezone)
    lines = [
        kind,
        f"Node ID: {config.node_id}",
        f"Performance: {fmt_percent(performance)}",
        f"Threshold: {fmt_percent(config.performance_threshold)}",
        f"Checked at: {now}",
        f"Source: {source_key}",
    ]
    if measured_at:
        lines.insert(4, f"Metric time: {measured_at}")
    return "\n".join(lines)


def main() -> int:
    config = load_config()
    log.info(
        "Starting Nym performance monitor: node_id=%s interval=%smin threshold=%s reports=%s tz=%s retries=%s",
        config.node_id,
        config.check_interval_minutes,
        config.performance_threshold,
        ",".join(config.report_times),
        config.timezone_name,
        config.api_retry_attempts,
    )

    next_check_at = datetime.now(timezone.utc)
    if not config.run_check_on_startup:
        next_check_at += timedelta(minutes=config.check_interval_minutes)

    last_alert_at: datetime | None = None
    sent_report_keys: set[str] = set()

    while not _STOP:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(config.timezone)

        # Mandatory daily status reports at exact configured HH:MM local time.
        current_hhmm = now_local.strftime("%H:%M")
        report_key = now_local.strftime("%Y-%m-%d") + " " + current_hhmm
        if current_hhmm in config.report_times and report_key not in sent_report_keys:
            try:
                performance, entry, source_key = fetch_performance(config)
                msg = build_status_message(config, performance, entry, source_key, "📊 Nym scheduled report")
                send_telegram(config, msg)
                sent_report_keys.add(report_key)
                log.info("Sent scheduled report for %s: %s", report_key, fmt_percent(performance))
            except Exception as exc:  # noqa: BLE001
                log.exception("Failed to send scheduled report: %s", exc)
                try:
                    send_telegram(
                        config,
                        build_api_failure_message(
                            config,
                            exc,
                            "⚠️ Nym scheduled report failed after retries",
                        ),
                    )
                    # Mark this scheduled slot as handled to avoid duplicate error messages
                    # every LOOP_SLEEP_SECONDS during the same HH:MM minute.
                    sent_report_keys.add(report_key)
                except Exception as telegram_exc:  # noqa: BLE001
                    log.exception("Could not notify Telegram about scheduled report failure: %s", telegram_exc)

        # Regular threshold check.
        if now_utc >= next_check_at:
            next_check_at = now_utc + timedelta(minutes=config.check_interval_minutes)
            try:
                performance, entry, source_key = fetch_performance(config)
                log.info("Current performance: %s", fmt_percent(performance))

                if performance < config.performance_threshold:
                    cooldown_ok = (
                        last_alert_at is None
                        or now_utc - last_alert_at >= timedelta(minutes=config.alert_cooldown_minutes)
                    )
                    if cooldown_ok:
                        msg = build_status_message(
                            config,
                            performance,
                            entry,
                            source_key,
                            "🚨 Nym performance alert",
                        )
                        send_telegram(config, msg)
                        last_alert_at = now_utc
                        log.warning("Sent low performance alert: %s", fmt_percent(performance))
                    else:
                        log.warning("Performance is low, but alert cooldown is active: %s", fmt_percent(performance))

            except Exception as exc:  # noqa: BLE001
                log.exception("Regular check failed after retries: %s", exc)
                # Forced notification: if all API retry attempts failed, notify Telegram
                # regardless of cooldown. Regular checks are already spaced by
                # CHECK_INTERVAL_MINUTES, so this should not spam on every loop tick.
                try:
                    send_telegram(
                        config,
                        build_api_failure_message(
                            config,
                            exc,
                            "⚠️ Nym regular check failed after retries",
                        ),
                    )
                except Exception as telegram_exc:  # noqa: BLE001
                    log.exception("Could not notify Telegram about error: %s", telegram_exc)

        # Prevent unbounded set growth after several days.
        if len(sent_report_keys) > 20:
            today = now_local.strftime("%Y-%m-%d")
            yesterday = (now_local - timedelta(days=1)).strftime("%Y-%m-%d")
            sent_report_keys = {k for k in sent_report_keys if k.startswith(today) or k.startswith(yesterday)}

        time.sleep(max(1.0, config.loop_sleep_seconds))

    log.info("Stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
