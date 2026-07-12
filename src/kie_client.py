"""Shared Kie.ai task client (video and image models use the same flow)."""

import json
import os
import re
import time

import requests

KIE_BASE = "https://api.kie.ai/api/v1"


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def get_credits(key: str) -> float:
    resp = requests.get(f"{KIE_BASE}/chat/credit", headers=_headers(key), timeout=30)
    body = resp.json()
    if body.get("code") != 200 or body.get("data") is None:
        raise RuntimeError(f"Kie.ai credit check failed: {body}")
    return float(body["data"])


def create_task(model: str, task_input: dict, key: str) -> str:
    resp = requests.post(
        f"{KIE_BASE}/jobs/createTask",
        headers=_headers(key),
        json={"model": model, "input": task_input},
        timeout=60,
    )
    body = resp.json()
    task_id = (body.get("data") or {}).get("taskId") or body.get("taskId")
    if not resp.ok or not task_id:
        raise RuntimeError(f"Kie.ai createTask failed ({model}): {resp.status_code} {body}")
    return task_id


def poll_task(task_id: str, key: str, exts: str = "mp4", timeout_s: int = 1200) -> str:
    """Poll until done; return the first result URL matching `exts` (regex alt)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(
            f"{KIE_BASE}/jobs/recordInfo",
            headers=_headers(key),
            params={"taskId": task_id},
            timeout=60,
        )
        body = resp.json()
        data = body.get("data") or {}
        state = (data.get("state") or "").lower()
        if state in ("success", "completed"):
            # Search only the result payload: the record also echoes the task
            # *inputs* under "param", whose image URLs would match first on
            # image-to-image tasks (e.g. keyframe edits)
            blob = data.get("resultJson") or json.dumps(
                {k: v for k, v in data.items() if k != "param"}
            )
            urls = re.findall(rf"https://[^\"\\\s]+?\.(?:{exts})[^\"\\\s]*", blob)
            if urls:
                return urls[0]
            raise RuntimeError(f"Kie.ai task succeeded but no result URL found: {body}")
        if state in ("fail", "failed", "error"):
            raise RuntimeError(f"Kie.ai task failed: {body}")
        time.sleep(10)
    raise RuntimeError(f"Kie.ai task {task_id} timed out after {timeout_s}s")


def download(url: str, path) -> None:
    with requests.get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
