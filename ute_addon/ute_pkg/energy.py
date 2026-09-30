"""Dated UTE ledger and external Energy statistics (never legacy sensor sums)."""

from __future__ import annotations

import asyncio
import hashlib
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

URUGUAY_TZ = ZoneInfo("America/Montevideo")
SCHEMA_VERSION = 2


def statistic_id_for(account_id: str) -> str:
    """Keep different accounts isolated without exposing the account number."""
    suffix = hashlib.sha256(account_id.strip().encode()).hexdigest()[:16]
    return f"ute_consumo:energia_{suffix}"


def history_start(state: dict[str, Any], account_id: str) -> date | None:
    """Requery the last recorded month to recover outages and current revisions."""
    if state.get("schema_version") != SCHEMA_VERSION:
        return None
    if state.get("statistic_id") != statistic_id_for(account_id):
        return None
    days = state.get("days", {})
    if not isinstance(days, dict):
        raise ValueError("Invalid UTE ledger; restore the add-on backup")
    if not days:
        return date.fromisoformat(state["start_date"]).replace(day=1)
    rows = build_statistics(state)
    if not rows:
        return date.fromisoformat(state["start_date"]).replace(day=1)
    latest_contiguous = (
        datetime.fromisoformat(rows[-1]["start"]).astimezone(URUGUAY_TZ).date()
    )
    return latest_contiguous.replace(day=1)


def _energy(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError("Invalid daily UTE energy value")
    return round(float(value), 2)


def _breakdown_matches(peak: float | None, off_peak: float | None, total: float) -> bool:
    """A tariff split is usable only when both sides were seen and sum to the total."""
    if peak is None or off_peak is None:
        return False
    return round(peak + off_peak, 2) == total


def _stored_tariffs(previous: dict[str, Any], key: str, same_ledger: bool) -> dict[str, float]:
    raw = previous.get(key) if same_ledger else None
    if not isinstance(raw, dict):
        return {}
    stored: dict[str, float] = {}
    for day, value in raw.items():
        try:
            stored[day] = _energy(value)
        except (TypeError, ValueError):
            continue
    return stored


def _optional_tariff(mapping: dict[str, Any], key: str) -> float | None:
    if key not in mapping or mapping[key] is None:
        return None
    return _energy(mapping[key])


def prepare_state(
    data: Any, previous: dict[str, Any], account_id: str
) -> tuple[dict[str, float | None], dict[str, Any]]:
    """Merge dated readings; a correction replaces a day, absence preserves it."""
    identifier = statistic_id_for(account_id)
    if not data.fecha_inicial or not data.fecha_final:
        raise ValueError("UTE period is required for a dated ledger")
    start = datetime.strptime(data.fecha_inicial, "%d-%m-%Y").date()
    end = datetime.strptime(data.fecha_final, "%d-%m-%Y").date()
    if start > end or end >= datetime.now(URUGUAY_TZ).date():
        raise ValueError("Invalid or incomplete UTE period")
    same_ledger = (
        previous.get("schema_version") == SCHEMA_VERSION
        and previous.get("statistic_id") == identifier
    )
    days = dict(previous.get("days", {})) if same_ledger else {}
    peak_days = _stored_tariffs(previous, "peak_days", same_ledger)
    off_peak_days = _stored_tariffs(previous, "off_peak_days", same_ledger)
    stored_anchor = (
        date.fromisoformat(previous["start_date"])
        if same_ledger and previous.get("start_date")
        else None
    )
    for key, value in days.items():
        day = date.fromisoformat(key)
        if day.isoformat() != key or day >= datetime.now(URUGUAY_TZ).date():
            raise ValueError("Invalid UTE ledger date")
        if stored_anchor is not None and day < stored_anchor:
            raise ValueError("Invalid UTE ledger anchor")
        _energy(value)
    # A requested month-start is not a reading. Anchor at the earliest confirmed
    # day so a missing day 1 cannot block the series forever. An empty previous
    # v2 ledger does not freeze that phantom start.
    confirmed = [date.fromisoformat(key) for key in days]
    if confirmed and stored_anchor is not None and stored_anchor.isoformat() in days:
        anchor: date | None = stored_anchor
    elif confirmed:
        anchor = min(confirmed)
    else:
        anchor = None
    incoming_peak = getattr(data, "daily_peak_energy_kwh", None)
    incoming_off = getattr(data, "daily_off_peak_energy_kwh", None)
    peak_in = incoming_peak if isinstance(incoming_peak, dict) else {}
    off_in = incoming_off if isinstance(incoming_off, dict) else {}
    for key, value in getattr(data, "daily_energy_kwh", {}).items():
        day = date.fromisoformat(key)
        # Recovery can span earlier months than the displayed monthly period.
        if (
            day.isoformat() != key
            or day > end
            or day >= datetime.now(URUGUAY_TZ).date()
        ):
            raise ValueError("Daily UTE date outside the completed period")
        anchor = day if anchor is None else min(anchor, day)
        total = _energy(value)
        days[key] = total
        supplied = key in peak_in or key in off_in
        if supplied:
            peak = _optional_tariff(peak_in, key)
            off_peak = _optional_tariff(off_in, key)
            if (
                peak is not None
                and off_peak is not None
                and _breakdown_matches(peak, off_peak, total)
            ):
                peak_days[key] = peak
                off_peak_days[key] = off_peak
            elif not _breakdown_matches(
                peak_days.get(key), off_peak_days.get(key), total
            ):
                peak_days.pop(key, None)
                off_peak_days.pop(key, None)
        elif not _breakdown_matches(peak_days.get(key), off_peak_days.get(key), total):
            # Corrected total without a refreshed split: drop the contradiction.
            # Never invent a replacement, and never keep an unseen tariff as zero.
            peak_days.pop(key, None)
            off_peak_days.pop(key, None)
    if anchor is None:
        anchor = stored_anchor or start
    peak_days = {
        key: value
        for key, value in peak_days.items()
        if key in days
        and _breakdown_matches(value, off_peak_days.get(key), days[key])
    }
    off_peak_days = {key: off_peak_days[key] for key in peak_days}
    latest = max(days) if days else None
    daily: dict[str, float | None]
    if latest:
        daily = {
            "peak": peak_days.get(latest),
            "off_peak": off_peak_days.get(latest),
            "total": days[latest],
        }
    else:
        daily = {"peak": None, "off_peak": None, "total": None}
    state = {
        "schema_version": SCHEMA_VERSION,
        "statistic_id": identifier,
        "start_date": anchor.isoformat(),
        "days": dict(sorted(days.items())),
        "peak_days": dict(sorted(peak_days.items())),
        "off_peak_days": dict(sorted(off_peak_days.items())),
        "daily_date": latest,
    }
    return daily, state


def build_statistics(state: dict[str, Any]) -> list[dict[str, Any]]:
    """One daily aggregate at local midnight; stop rather than invent missing days.

    This is a daily-resolution series, not an hourly consumption estimate.
    Corrections rebuild cumulative sums for every subsequent known day.
    """
    days = state["days"]
    if not days:
        return []
    day = date.fromisoformat(state["start_date"])
    end = date.fromisoformat(max(days))
    total = 0.0
    rows = []
    while day <= end:
        if day.isoformat() not in days:
            break
        total = round(total + _energy(days[day.isoformat()]), 2)
        start = datetime.combine(day, time.min, URUGUAY_TZ).astimezone(timezone.utc)
        rows.append({"start": start.isoformat(), "sum": total, "state": total})
        day += timedelta(days=1)
    return rows


def _row_key(row: dict[str, Any]) -> int:
    return round(datetime.fromisoformat(row["start"]).timestamp() * 1000)


def _ledger_midnight_keys(state: dict[str, Any]) -> set[int]:
    """Exact local-midnight keys for every confirmed ledger day."""
    days = state.get("days") or {}
    if not isinstance(days, dict):
        return set()
    keys: set[int] = set()
    for key in days:
        start = datetime.combine(date.fromisoformat(key), time.min, URUGUAY_TZ)
        keys.add(round(start.astimezone(timezone.utc).timestamp() * 1000))
    return keys


def _matches(existing: list[dict[str, Any]], expected: list[dict[str, Any]]) -> bool:
    sums = {round(row["start"]): row.get("sum") for row in existing}
    if len(existing) != len(expected) or len(sums) != len(expected):
        return False
    for row in expected:
        value = sums.get(_row_key(row))
        if not isinstance(value, (int, float)) or not math.isclose(
            value, row["sum"], rel_tol=0, abs_tol=1e-6
        ):
            return False
    return True


def _pending_coverage(
    state: dict[str, Any], rows: list[dict[str, Any]]
) -> tuple[int, str | None]:
    """Known days after the first gap are pending; they are not imported yet."""
    days = state.get("days") or {}
    if not isinstance(days, dict) or not days:
        return 0, None
    if not rows:
        first = state.get("start_date") or min(days)
        return sum(1 for key in days if key > first), str(first)
    last = datetime.fromisoformat(rows[-1]["start"]).astimezone(URUGUAY_TZ).date()
    later = [key for key in days if date.fromisoformat(key) > last]
    if not later:
        return 0, None
    return len(later), (last + timedelta(days=1)).isoformat()


def _sync_status(
    rows: list[dict[str, Any]], pending_days: int, first_missing: str | None
) -> dict[str, Any]:
    if not rows and pending_days == 0:
        status = "waiting"
    elif pending_days:
        status = "pending"
    else:
        status = "verified"
    return {
        "status": status,
        "imported_days": len(rows),
        "pending_days": pending_days,
        "first_missing_date": first_missing,
    }


async def sync_statistics(
    call: Callable[[dict[str, Any]], Awaitable[Any]], state: dict[str, Any]
) -> dict[str, Any]:
    """Read, import only our isolated ID, then verify actual recorder rows.

    HA acknowledges queueing, not completion. A recorder date that is not a
    confirmed ledger day at exact local midnight is refused. Known dates that
    cannot yet be reconstructed because of an internal gap are left untouched
    and reported as waiting_for_gap — never imported as a partial prefix.
    An empty ledger is waiting, not verified. An internal gap with no later
    recorder rows verifies only the contiguous prefix and reports later known
    days as pending.
    """
    rows = build_statistics(state)
    pending_days, first_missing = _pending_coverage(state, rows)
    identifier = state["statistic_id"]
    if not identifier.startswith("ute_consumo:energia_"):
        raise ValueError("Unsafe UTE statistic ID")
    query = {
        "type": "recorder/statistics_during_period",
        "start_time": "1970-01-01T00:00:00+00:00",
        "statistic_ids": [identifier],
        "period": "hour",
        "types": ["sum"],
    }
    existing = (await call(query)).get(identifier, [])
    known_keys = _ledger_midnight_keys(state)
    if any(round(row["start"]) not in known_keys for row in existing):
        raise ValueError(
            "Recorder history exceeds the UTE ledger; restore the matching add-on backup or recover missing dates"
        )
    prefix_keys = {_row_key(row) for row in rows}
    if any(round(row["start"]) not in prefix_keys for row in existing):
        # The suffix is still in the ledger, but a hole blocks cumulative
        # reconstruction. Importing the earlier prefix would leave those
        # preserved rows with the old anchor's sums.
        confirmed = state.get("days") or {}
        return {
            "status": "waiting_for_gap",
            "imported_days": 0,
            "pending_days": len(confirmed) if isinstance(confirmed, dict) else 0,
            "first_missing_date": first_missing,
            "preserved_days": len(existing),
        }
    if rows and not _matches(existing, rows):
        await call(
            {
                "type": "recorder/import_statistics",
                "metadata": {
                    "statistic_id": identifier,
                    "source": "ute_consumo",
                    "name": "UTE Consumo diario",
                    "unit_of_measurement": "kWh",
                    "unit_class": "energy",
                    "mean_type": 0,
                    "has_sum": True,
                },
                "stats": rows,
            }
        )
        verified = False
        for _ in range(12):
            existing = (await call(query)).get(identifier, [])
            if _matches(existing, rows):
                verified = True
                break
            await asyncio.sleep(0.5)
        if not verified:
            raise RuntimeError(
                "UTE import queued but recorder rows could not be verified; retry on the next scan"
            )
    return _sync_status(rows, pending_days, first_missing)
