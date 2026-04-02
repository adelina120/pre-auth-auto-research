import os
import re
import json
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import threading
import random
from contextlib import contextmanager
import requests
from dotenv import load_dotenv
from browser_use_sdk import AsyncBrowserUse # pyright: ignore[reportMissingImports]

load_dotenv()
raw_api_key: Optional[str] = os.getenv("BROWSER_USE_API_KEY")
if raw_api_key is None or not raw_api_key.strip():
    raise RuntimeError("BROWSER_USE_API_KEY not found in environment")
api_key: str = raw_api_key.strip()
client = AsyncBrowserUse()

# Configurable server base URL (public endpoints, no auth required)
BASE_URL ="https://wes-wgs-pa-app-u2c8s.ondigitalocean.app"

# Browser-Use Cloud API base (v2)
API_BASE = os.getenv("BROWSER_USE_API_BASE", "https://api.browser-use.com/api/v2").rstrip("/")

# Concurrency guard for Browser-Use sessions/tasks
MAX_ACTIVE_SESSIONS = int(os.getenv("BROWSER_USE_MAX_SESSIONS", "250"))
_SESSION_SEMAPHORE = threading.Semaphore(MAX_ACTIVE_SESSIONS)

def _api_headers() -> Dict[str, str]:
    return {
        "X-Browser-Use-API-Key": api_key,
        "Content-Type": "application/json",
    }

def _request_with_retries(method: str, url: str, *, headers: Dict[str, str], json: Optional[Dict] = None,
                          timeout: int = 30, max_retries: int = 5) -> requests.Response:
    backoff = 1.0
    last_resp: Optional[requests.Response] = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, headers=headers, json=json, timeout=timeout)
            last_resp = resp
        except requests.RequestException:
            if attempt >= max_retries - 1:
                raise
            time.sleep(backoff + random.uniform(0.0, 0.5))
            backoff = min(backoff * 2.0, 20.0)
            continue

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait_seconds = backoff
            if retry_after:
                try:
                    wait_seconds = float(retry_after)
                except ValueError:
                    wait_seconds = backoff
            time.sleep(wait_seconds + random.uniform(0.0, 0.5))
            backoff = min(backoff * 2.0, 20.0)
            continue

        if resp.status_code >= 500 and attempt < max_retries - 1:
            time.sleep(backoff + random.uniform(0.0, 0.5))
            backoff = min(backoff * 2.0, 20.0)
            continue

        return resp

    if last_resp is not None:
        return last_resp
    raise RuntimeError("Request failed without a response")

@contextmanager
def _session_limit():
    _SESSION_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _SESSION_SEMAPHORE.release()

def create_task(task_text: str, llm: str, max_steps: int, metadata: Optional[Dict[str, object]] = None) -> str:
    """Create and start a task and return task ID.
    Metadata, when provided, is sent to Browser-Use Cloud so it
    is echoed back on subsequent task API responses (e.g. patient_id).
    """
    payload = {
        "task": task_text,
        "llm": llm,
        "thinking": True,
        "vision": True, 
        "maxSteps": max_steps,
        "allowedDomains": [BASE_URL.split("//", 1)[-1]]
    }
    if metadata:
        payload["metadata"] = metadata
    resp = _request_with_retries("POST", f"{API_BASE}/tasks", headers=_api_headers(), json=payload, timeout=30)
    # 202 Accepted on success
    if resp.status_code not in (200, 202):
        print(f"[create_task] {resp.status_code} response body: {resp.text[:500]}")
        resp.raise_for_status()
    return resp.json()["id"]

def get_task(task_id: str) -> Dict:
    resp = _request_with_retries("GET", f"{API_BASE}/tasks/{task_id}", headers=_api_headers(), timeout=60, max_retries=3)
    resp.raise_for_status()
    return resp.json()

def wait_for_task(task_id: str, poll_interval: float = 2.0, timeout_seconds: int = 600) -> Dict:
    """Poll the task until finished or timeout; return final task JSON."""
    deadline = time.time() + timeout_seconds
    last = {}
    while time.time() < deadline:
        try:
            last = get_task(task_id)
            status = (last.get("status") or "").lower()
            if status in {"finished", "stopped"}:
                return last
        except requests.RequestException:
            pass
        time.sleep(poll_interval)
    return last

def _split_name(full_name: str) -> Tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]

def _filename_from_disposition(disposition: Optional[str]) -> Optional[str]:
    if not disposition:
        return None
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition)
    return m.group(1).strip() if m else None

def get_submission_by_patient(session: requests.Session, base_url: str, first_name: str, last_name: str, llm:str,
                              patient_id: str, task_id: str, sample_type: str, dest_dir: Path) -> Optional[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = session.post(f"{base_url}/download/patient", json={
        "patient_first_name": first_name,
        "patient_last_name": last_name
    }, stream=True)

    if resp.status_code == 404:
        return None

    resp.raise_for_status()

    filename = _filename_from_disposition(resp.headers.get("Content-Disposition")) or f"submission_{uuid.uuid4().hex}.json"

    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type and "attachment" not in (resp.headers.get("Content-Disposition") or "").lower():
        try:
            body_json = resp.json()
        except ValueError:
            return None
        if body_json.get("file") is None:
            return None
    try:
        body = json.loads(resp.content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    payload = body.get("payload")
    if payload is None:
        return None

    body["task_id"] = task_id
    body["patient_id"] = patient_id
    body["sample_type"] = sample_type
    body["llm"] = llm

    out_path = dest_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)

    # Attempt to delete the server-side submission using the filename
    try:
        delete_submission(session, base_url, filename)
    except Exception:
        pass
    return out_path

def delete_submission(session: requests.Session, base_url: str, filename: str) -> None:
    resp = session.post(f"{base_url}/delete", json={"filename": filename})
    if resp.status_code != 200:
        raise RuntimeError(f"Delete failed for {filename}: {resp.status_code} {resp.text}")
    body = {}
    try:
        body = resp.json()
    except Exception:
        pass
    if not body.get("ok", False):
        raise RuntimeError(f"Delete failed for {filename}: {body}")

def execute_one_patient(prompt, patient_name, patient_id, sample_type, llm, max_steps: int, output_dir: Path) -> Dict:
    task_metadata: Dict[str, object] = {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "sample_type": sample_type,
    }
    with _session_limit():
        task_id = create_task(task_text=prompt, llm=llm, max_steps= max_steps, metadata=task_metadata)
        final_task = wait_for_task(task_id)
    session = requests.Session()
    first, last = _split_name(patient_name)
    local_dir = output_dir
    saved_path = get_submission_by_patient(session, BASE_URL, first, last, llm, 
                                           patient_id, task_id, sample_type, local_dir)
    filename = saved_path.name if saved_path else None
    if saved_path:
        try:
            delete_submission(session, BASE_URL, saved_path.name)
        except Exception:
            pass
    return {
        "patient": patient_name,
        "task_id": task_id,
        "filename": filename,
        "saved_path": str(saved_path) if saved_path else None,
        "llm": llm,
    }

