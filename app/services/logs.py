"""Match preserved report text to mock CloudWatch events using words and time.

load_log_entries(start_time, end_time) is the replaceable retrieval boundary.
A future CloudWatch adapter can return the same normalized records.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from app import config

log = logging.getLogger("uat.logs")
NO_SUPPORTING_LOGS = "No supporting logs found"
CHECKED_CATEGORIES = {"bug", "awkward"}
STOP_WORDS = set("a an the and or but to of in on at for from with by is it its this that was were are be been as i we my our they their you your when after before then just not no didnt doesnt couldnt cant cannot could should would have has had do does did work working worked issue problem something wrong error happened actual expected behaviour page screen button report reports section try trying click clicked text type mobile device browser service request response failed failure".split())
# Transparent concept expansion handles common tester and service vocabulary.
CONCEPTS = {
    "export": {"export", "exportservice", "download"},
    "login": {"login", "signin", "authentication", "authservice", "token", "password"},
    "invoice": {"invoice", "invoices", "invoicerenderer"},
    "save": {"save", "saving", "settingsservice"},
    "details": {"detail", "details", "detailsection", "detailservice", "editing", "edit"},
    "timeout": {"timeout", "timed", "hang", "hangs", "hanging", "spinner", "spinning", "loading", "froze", "frozen", "stuck"},
}


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("A timezone is required")
    return parsed.astimezone(timezone.utc)


def keywords(text: str) -> set[str]:
    split = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    words = set(re.findall(r"[a-z0-9]+", split.lower())) - STOP_WORDS
    for concept, alternatives in CONCEPTS.items():
        if words & alternatives:
            words.add(concept)
    return words


def load_log_entries(start_time: datetime, end_time: datetime) -> list[dict]:
    """Mock source. The window arguments support replacing this with CloudWatch."""
    entries = json.loads(config.MOCK_LOGS_PATH.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("Expected a list of events")
    return entries


def _windows(reports: list[dict], minutes: int) -> list[dict]:
    result = []
    for report in reports:
        reference = report.get("occurred_at") or report.get("created_at")
        if not reference:
            continue
        try:
            at = parse_timestamp(reference)
        except (TypeError, ValueError, AttributeError):
            continue
        text = "\n".join(str(value) for value in (report.get("answers") or {}).values())
        if report.get("follow_up_answer"):
            text += "\n" + report["follow_up_answer"]
        for reply in report.get("manager_clarifications") or []:
            if reply.get("answer"):
                text += "\n" + reply["answer"]
        result.append({
            "report_id": str(report["id"]),
            "at": at,
            "start": at - timedelta(minutes=minutes),
            "end": at + timedelta(minutes=minutes),
            "basis": "occurrence" if report.get("occurred_at") else "submission",
            "terms": keywords(text),
        })
    return result


def _normalize(entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("Expected an event object")
    required = ("timestamp", "level", "service", "message")
    if any(not isinstance(entry.get(key), str) or not entry[key].strip() for key in required):
        raise ValueError("Invalid event fields")
    at = parse_timestamp(entry["timestamp"])
    code = entry.get("error_code")
    if code is not None and not isinstance(code, str):
        raise ValueError("Invalid error code")
    return {key: entry[key] for key in required} | {
        "timestamp": at.isoformat(), "level": entry["level"].upper(), "error_code": code,
    }


def find_supporting_logs(reports: list[dict], category: str, *, entries=None,
                         window_minutes=None, limit=None) -> dict:
    """Return relevance evidence. Empty evidence says nothing about bug validity."""
    if category not in CHECKED_CATEGORIES:
        return {"status": "skipped", "reason": "category", "matches": []}
    minutes = config.LOG_WINDOW_MINUTES if window_minutes is None else window_minutes
    maximum = config.LOG_MATCH_LIMIT if limit is None else limit
    windows = _windows(reports, minutes)
    if not windows:
        return {"status": "unavailable", "reason": "invalid_report_time", "matches": [],
            "message": "Log evidence unavailable. No usable occurrence or submission time was found."}
    try:
        raw = entries if entries is not None else load_log_entries(
            min(window["start"] for window in windows), max(window["end"] for window in windows)
        )
        normalized = [_normalize(entry) for entry in raw]
    except Exception as exc:
        log.warning("Mock log retrieval failed: %s", type(exc).__name__)
        return {"status": "unavailable", "reason": "log_source_error", "matches": [],
            "message": "Log evidence unavailable. Try refreshing the final report."}

    matches = []
    seen = set()
    for entry in normalized:
        identity = tuple(entry[key] for key in ("timestamp", "service", "message", "error_code"))
        if identity in seen:
            continue
        seen.add(identity)
        # Routine success messages are noise, not supporting error evidence.
        if entry["level"] not in {"WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"}:
            continue
        at = parse_timestamp(entry["timestamp"])
        terms = keywords(" ".join([entry["service"], entry["message"], entry["error_code"] or ""]))
        relevant = []
        for window in windows:
            if not (window["start"] <= at <= window["end"]):
                continue
            shared = window["terms"] & terms
            # A generic timeout alone cannot link two different services/problems.
            distinctive = shared - {"timeout"}
            if not distinctive:
                continue
            delta = abs((at - window["at"]).total_seconds())
            coverage = min(1.0, len(shared) / min(max(len(window["terms"]), 1), 6))
            proximity = 1 - delta / (minutes * 60)
            score = round(min(1.0, .75 * coverage + .25 * proximity), 4)
            if score >= config.LOG_MIN_RELEVANCE:
                relevant.append((score, delta, window, shared))
        if not relevant:
            continue
        best = max(relevant, key=lambda item: item[0])
        score, delta, window, shared = best
        terms_text = ", ".join(sorted(shared))
        reasoning = (f"Shared terms or concepts: {terms_text}. Event is {delta / 60:.1f} minutes "
            f"from a report's {window['basis']} time.")
        matches.append({**entry, "relevance_score": score, "reasoning": reasoning,
            "report_ids": sorted({item[2]["report_id"] for item in relevant})})
    matches.sort(key=lambda item: (-item["relevance_score"], item["timestamp"], item["service"], item["message"]))
    result = {
        "status": "ok", "source": "mock_cloudwatch", "matches": matches[:maximum],
        "message": "Supporting log evidence found" if matches else NO_SUPPORTING_LOGS,
        "window_minutes": minutes,
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "time_references": [{"report_id": window["report_id"], "time": window["at"].isoformat(),
            "basis": window["basis"]} for window in windows],
    }
    if normalized:
        timestamps = sorted(entry["timestamp"] for entry in normalized)
        result.update(session_start=timestamps[0], session_end=timestamps[-1])
    return result
