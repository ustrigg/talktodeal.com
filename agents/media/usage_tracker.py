"""Token usage tracker — thread-safe, logs to local JSON file."""

import json
import os
import threading
import time

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "usage_log.json")
_lock = threading.Lock()

# GPT-4.1-mini pricing per 1K tokens
_COST_PER_1K = {
    "prompt": 0.0004,       # $0.40/M input
    "completion": 0.0016,   # $1.60/M output
}


def record_usage(session_id: str, step: str, prompt_tokens: int, completion_tokens: int):
    """Record a single GPT API call. Thread-safe."""
    cost = round(
        prompt_tokens / 1000 * _COST_PER_1K["prompt"]
        + completion_tokens / 1000 * _COST_PER_1K["completion"],
        6,
    )
    entry = {
        "session_id": session_id,
        "step": step,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "timestamp": time.time(),
    }

    with _lock:
        data = _load()
        data["records"].append(entry)
        t = data["totals"]
        t["prompt_tokens"] += prompt_tokens
        t["completion_tokens"] += completion_tokens
        t["total_tokens"] += prompt_tokens + completion_tokens
        t["cost"] = round(t["cost"] + cost, 6)
        t["api_calls"] += 1
        _save(data)

    print(f"[Usage] {step} | in={prompt_tokens} out={completion_tokens} cost=${cost:.4f} | session={session_id[:20]}")
    return entry


def get_session_summary(session_id: str) -> dict:
    """Get usage breakdown for a single session."""
    with _lock:
        data = _load()

    entries = [e for e in data["records"] if e["session_id"] == session_id]
    if not entries:
        return {"session_id": session_id, "total_calls": 0}

    by_step = {}
    total_p = total_c = 0
    total_cost = 0.0

    for e in entries:
        step = e["step"]
        if step not in by_step:
            by_step[step] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}
        by_step[step]["calls"] += 1
        by_step[step]["prompt_tokens"] += e["prompt_tokens"]
        by_step[step]["completion_tokens"] += e["completion_tokens"]
        by_step[step]["cost"] += e["cost"]
        total_p += e["prompt_tokens"]
        total_c += e["completion_tokens"]
        total_cost += e["cost"]

    return {
        "session_id": session_id,
        "total_calls": len(entries),
        "prompt_tokens": total_p,
        "completion_tokens": total_c,
        "total_tokens": total_p + total_c,
        "cost": round(total_cost, 4),
        "by_step": by_step,
    }


def get_totals() -> dict:
    """Get global cumulative totals."""
    with _lock:
        return _load()["totals"]


def _load() -> dict:
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"records": [], "totals": {
        "prompt_tokens": 0, "completion_tokens": 0,
        "total_tokens": 0, "cost": 0.0, "api_calls": 0,
    }}


def _save(data: dict):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
