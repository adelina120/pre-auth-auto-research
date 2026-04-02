""" Pre browser use submission processing and post browser use submission processing helper functions."""

from asyncio.log import logger
import datetime
import json
import os
import random
from typing import Dict, List, Optional
from pathlib import Path
import pytz
import requests

API_BASE = os.getenv("BROWSER_USE_API_BASE", "https://api.browser-use.com/api/v2").rstrip("/")
raw_api_key = os.getenv("BROWSER_USE_API_KEY")
if raw_api_key is None or not raw_api_key.strip():
    raise RuntimeError("BROWSER_USE_API_KEY not found in environment")
api_key: str = raw_api_key.strip()

BUDGET_PER_RUN = 50
TOTAL_BUDGET = 500

def _api_headers() -> Dict[str, str]:
    return {
        "X-Browser-Use-API-Key": api_key,
        "Content-Type": "application/json",
    }

# Pre-submission processing functions
def load_experiment_profiles(n, sample_type: List[str], path: str):
	"""
	Load all_samples.json and pick n random profiles from each sample_type.
	Args:
		n (int): Number of profiles to pick per sample_type.
		path (str): Path to the JSON file.
	Returns:
		List of selected profiles (dicts).
	"""
	with open(path, "r", encoding="utf-8") as f:
		samples = json.load(f)
	grouped = {}
	for sample in samples:
		st = sample["sample_type"]
		if st not in grouped:
			grouped[st] = []
		grouped[st].append(sample)
	selected = []
	for st in sample_type:
		group = grouped.get(st, [])
		if len(group) <= n:
			selected.extend(group)
		else:
			selected.extend(random.sample(group, n))
	return selected

def create_jobs(n, llm: str, input_path: str):
    profiles = load_experiment_profiles(n, ['1','2a','2b','2c','3a','3b','4'], input_path)
    jobs = []
    for profile in profiles:
        job = {
            "patient_id": profile["patient_id"],
            "first_name": profile["first_name"],
            "last_name": profile["last_name"],
            "sample_type": profile["sample_type"],
            "llm": llm,
        }
        jobs.append(job)
    return jobs

# Post-submission processing functions
def get_task(task_id: str) -> Dict:
    resp = requests.get(f"{API_BASE}/{task_id}", headers=_api_headers(), timeout=60)
    resp.raise_for_status()
    result = resp.json()
    metadata = result.get("metadata", {})
    return {
         "task_id": task_id,
         "llm": result.get("llm"),
         "isSuccess": result.get("isSuccess"),
         "output": result.get("output"),
         "cost": result.get("cost"),
         "duration": result.get("duration"),
         "number_of_steps": len(result.get("steps", [])),
         "patient_id": metadata.get("patient_id"),
         "sample_type": metadata.get("sample_type"),
         "patient_name": metadata.get("patient_name"),
    }

def get_tasks(start_et: str, end_et: str):
    """
    Fetches all tasks from Browser Use Cloud within a given Eastern Time range.

    Args:
        start_et: start time in ET as ISO string e.g. "2026-01-01T08:00:00"
        end_et:   end time in ET as ISO string e.g. "2026-01-01T12:00:00"

    Returns:
        List of dicts with keys: id, llm, startedAt, finishedAt, isSuccess, cost
    """

    # Convert ET to UTC
    et_zone = pytz.timezone("US/Eastern")
    utc_zone = pytz.utc

    start_dt = et_zone.localize(datetime.datetime.fromisoformat(start_et)).astimezone(utc_zone)
    end_dt   = et_zone.localize(datetime.datetime.fromisoformat(end_et)).astimezone(utc_zone)

    # ISO 8601 strings required by API (ending with "Z" for UTC)
    after_utc  = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    before_utc = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    tasks_out = []
    page = 1
    page_size = 100  # maximum allowed

    while True:
        params = {
            "after": after_utc,
            "before": before_utc,
            "pageSize": page_size,
            "pageNumber": page
        }

        resp = requests.get(API_BASE, headers=_api_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            break

        # Extract & shape required attributes
        for task in items:
            tasks_out.append({
                "id": task.get("id"),
                "llm": task.get("llm"),
                "isSuccess": task.get("isSuccess"),
                "output": task.get("output"),
                "cost": task.get("cost"),
                "metadata": task.get("metadata", {})
            })

        # break if we've reached total pages
        if len(items) < page_size:
            break
        page += 1

    try:
        results_dir = Path(__file__).resolve().parents[2] / "data" / "experiment_results"
        results_dir.mkdir(parents=True, exist_ok=True)
        output_path = results_dir / "all_tasks.json"
        existing_tasks: List[Dict] = []
        if output_path.exists():
            with output_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                existing_tasks = loaded

        merged_by_id: Dict[str, Dict] = {}
        for task in existing_tasks:
            task_id = str(task.get("id", "")).strip()
            if task_id:               
                merged_by_id[task_id] = task
        for task in tasks_out:
            task_id = str(task.get("id", "")).strip()
            if task_id:
                merged_by_id[task_id] = task

        merged_tasks = list(merged_by_id.values())
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(merged_tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to write tasks to file: %s", e)
    return tasks_out

def get_experiement_cost(experiment_results: list[dict]):
    total_cost = sum(task.get("cost", 0) for task in experiment_results)
    return total_cost

# Evaluation functions
def neg_errors(task_outcomes):
    neg_count =  [task for task in task_outcomes if task.get("sample_type") in {"2a", "2b", "2c", "3b", "4"}]
    error_counts = 0
    for task in neg_count:
        if task.get("correct_withholding") is False:
            error_counts += 1
    return error_counts / len(neg_count) if neg_count else 0

def pos_errors(task_outcomes):
    pos_count =  [task for task in task_outcomes if task.get("sample_type") in {"1", "3a"}]
    error_counts = 0
    for task in pos_count:
        if task.get("non_groundtruth_withholding") is True:
            error_counts += 1
    return error_counts / len(pos_count) if pos_count else 0

def completion_rate(task_outcomes):
    completed_count = sum(1 for task in task_outcomes if task.get("completed") is True)
    return completed_count / len(task_outcomes) if task_outcomes else 0

def experiment_results(task_outcomes):
    error_rate = 0.5*neg_errors(task_outcomes) + 0.5*pos_errors(task_outcomes)
    return {
        "CompletionRate": completion_rate(task_outcomes),
        "ErrorRate": error_rate,
        "NegErrors": neg_errors(task_outcomes),
        "PosErrors": pos_errors(task_outcomes),
        "Cost": get_experiement_cost(task_outcomes)
    }