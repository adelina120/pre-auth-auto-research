import csv
import logging
from typing import Dict, List
from prepare.other_preps import create_jobs, experiment_results, get_task
from prepare.browser_use_submissions import execute_one_patient
from prepare.process_browser_use_output import process_all_messages
from agent_edit import create_browser_use_prompt, LLM, max_steps
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

logger = logging.getLogger(__name__)
root_dir = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description="Run experiment")
parser.add_argument("--input", default=str(root_dir / "all_samples.json"), help="Input samples JSON path")
parser.add_argument("--submitted-dir", default=str(root_dir / "data" / "submissions"), help="Output directory for downloaded submissions")
parser.add_argument("--workers", type=int, default=25, help="Max concurrent workers")
parser.add_argument("--llm", default=LLM, help="LLM model to run")
parser.add_argument("--max-steps", type=int, default=max_steps, help="Maximum steps per browser task")
parser.add_argument("--batch-input-path", default=str(root_dir / "data" / "batch_input.json"), help="Path to batch input JSON file")
parser.add_argument("--tasks-output-path", default=str(root_dir / "data" / "tasks_output.json"), help="Path to output JSON file for tasks")
parser.add_argument("--experiment-output-dir", default=str(root_dir / "data" / "experiment_results.tsv"), help="Output directory for experiment results")
args = parser.parse_args()

BASE_URL = "https://wes-wgs-pa-app-u2c8s.ondigitalocean.app/login"

def run_parallel_jobs(jobs: List[Dict], prompt:str, workers: int, max_steps: int, output_dir: Path) -> List[Dict]:
    """Run a list of jobs in parallel. Each job: {patient_name, patient_id, sample_type, llm}."""
    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for job in jobs:
            patient_name = job.get("patient_name", "")
            patient_id = job.get("patient_id")
            sample_type = job.get("sample_type")
            llm = job.get("llm")
            prompt = create_browser_use_prompt(BASE_URL, patient_name)
            futures[pool.submit(execute_one_patient, prompt, patient_name, patient_id, sample_type, llm, max_steps, output_dir)] = (patient_name, llm)

        for fut in as_completed(futures):
            task_id, patient, llm = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"task_id": task_id, "patient": patient, "llm": llm, "error": str(e)})
    return results

def get_all_tasks(task_ids: List[str]) -> List[Dict]:
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(get_task, task_id): task_id for task_id in task_ids}
        tasks = []
        for fut in as_completed(futures):
            try:
                tasks.append(fut.result())
            except Exception as e:
                logger.error(f"Failed to fetch task {futures[fut]}: {e}")
    return tasks

def write_experiment_reports(task_outcomes: List[Dict], output_path: Path, llm: str, max_steps: int):
    TSV_COLUMNS = ["experiment_idx", "llm", "max_steps", "CompletionRate", "ErrorRate", "NegErrors", "PosErrors", "Cost", "status", "failed_reason"]
    results = experiment_results(task_outcomes)
    total_cost = sum(float(task.get("cost") or 0) for task in task_outcomes)
    results["status"] = "PASSED"
    results["failed_reason"] = ""
    if total_cost > 50:
        results["status"] = "FAILED"
        results["failed_reason"] = f"Total cost for this experiment is more than 50: {total_cost:.2f}"
    if results["CompletionRate"] < 0.7:
        results["status"] = "FAILED"
        if results["failed_reason"]:
            results["failed_reason"] += "; "
        results["failed_reason"] += f"Completion rate of this experiment is less than 0.7: {results['CompletionRate']:.2f}"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    write_header = not output_path.exists()
    experiment_idx = 1
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
            if rows:
                experiment_idx = int(rows[-1]["experiment_idx"]) + 1

    row = {"experiment_idx": experiment_idx, "llm": llm, "max_steps": max_steps, **results}

    with output_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TSV_COLUMNS, delimiter="\t")
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    logger.info(f"Experiment {experiment_idx} written to {output_path} — status: {results['status']}")
    return experiment_idx

def write_tasks_to_json(updated_task_outcomes: List[Dict], output_path: Path, experiment_idx: int):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            existing = json.load(f)
    tagged = [{**task, "experiment_idx": experiment_idx} for task in updated_task_outcomes]
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(existing + tagged, f, indent=2)


if __name__ == "__main__":
    output_dir = Path(args.output_dir)
    batch_input_path = Path(args.batch_input_path)
    tasks_output_path = Path(args.tasks_output_path)
    exp_results_path = Path(args.experiment_output_dir)

    jobs = create_jobs(n=1, llm=args.llm, input_path=args.input)

    submission_results = run_parallel_jobs(
        jobs, prompt="", workers=args.workers, max_steps=args.max_steps, output_dir=output_dir
    )

    task_ids = [res["task_id"] for res in submission_results if res.get("task_id") is not None]
    raw_task_outcomes = get_all_tasks(task_ids)
    updated_task_outcomes = process_all_messages(raw_task_outcomes, str(batch_input_path))
    experiment_idx = write_experiment_reports(updated_task_outcomes, exp_results_path, llm=args.llm, max_steps=args.max_steps)
    write_tasks_to_json(updated_task_outcomes, tasks_output_path, experiment_idx)
    logger.info(f"Wrote {len(updated_task_outcomes)} tasks to {tasks_output_path}")

