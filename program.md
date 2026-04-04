You are an autonomous research agent optimizing a browser-based AI agent from Browser Use Cloud that submits pre-authorization forms for Whole Exome Sequencing (WES) and Whole Genome Sequencing (WGS). Your job is to iteratively improve the parameters in agent_edit.py so it makes better submission decisions.

## Repository Structure
prepare 
   `browser_use_submission.py`            — LOCKED. Submit webforms on Browser Use Cloud
   `other_preps.py`                       — LOCKED. Load sample data and evauluate metrics
   `process_browser_use_output.py`        — LOCKED. Process browser use agent output messages with OpenAI
`run_experiment.py`                       — LOCKED. Orchestrates a single experiment end-to-end.
`agent_edit.py`                           — EDITABLE. The ONLY file you modify.
data
   `groundtruth.json`                      — LOCKED. Ground truth labels for all patient profiles.
   `all_samples.json`                      — LOCKED. Complete patient data with different types to choose subset from
data/experiments/                       
   `experiment_results.tsv`               — Running log of all experiments (untracked by git).
   `tasks_output.json`                    — Records of the raw output from Browser Use & OpenAI

## What You Can Modify
Only `agent_edit.py` can be modified. This file contains:
- `create_browser_use_prompt(BASE_URL, patient_name)` — the main instructions given to the browser agent
- `LLM` —  which LLM powers the browser agent
- `max_steps` — max number of steps allowed for the browser use agent to complete the task
ALL other scripts in the repo can NOT be modified.

## The Task
There are 7 types of patient profiles:
- **Type 1**: Standard valid profile. Should be submitted.
- **Type 2a**: Subscriber is only 10–12 years older than patient (implausibly young as the parent or legal guardian). Submission should be withheld and issue should be reported by the browser agent.
- **Type 2b**: Prior test date falls after specimen collection date (chronological impossibility). Submission should be withheld.
- **Type 2c**: Specimen collection date (a required field) is intentionally missing. Should be withheld.
- **Type 3a**: Valid profile with partially genetically-irrelevant but legitimate clinical information. Should be submitted.
- **Type 3b**: Clinical information is unrelated to genetic testing (e.g., concussion). Should be withheld.
- **Type 4**: Two patient profiles share identical names. Should be withheld pending clarification.

The browser-use agent receives a prompt for pre-authorization form submission. The patient name will be proivded
in each prompt such that the browser agent can search for the patient's profile and get relevant information. The browser agent is expected to:
1. **Submit** the pre-authorization form with correct field values, OR
2. **Withhold** submission when the profile contains an intentional issue
However, the browser agent may also fail to complete the task due to technical issues (e.g., reaching max number of steps allowed, losing data etc.) or stop submission because it identifies issues other than what's intentaionlly designed (e.g., misinterpreted / hallucinated information)

## The Metric
The browser use agent will return a output message for each task which is then processed using OpenAI. The following boolean fields are defined:
   - `completed`: set to *false* if the the browser agent fails to complete the task, otherwise *true*
   - `submitted`: the pre-authorization form is submitted
   - `correct_withholding`: **applies to type 2a, 2b, 2c, 3b, 4 only**, set to *true* ONLY if the agent correctly stops the form submission and identifies the intentionally designed issues; otherwise *false*
   - `non_groundtruth_withholding`: the agent halts submission due to issues not intentionally designed

The primary metric is `error_rate` - the lower the better.
`error_rate` is calculated over all **completed** tasks only:
```
error_rate = (negative_error_counts + positive_error_counts) / completed_count
```

- **negative_error_counts**: tasks of type 2a, 2b, 2c, 3b, or 4 where `correct_withholding` is `false` — the agent should have withheld and identify the designed issues but did not do so correctly.
- **positives_error_counts**: tasks of type 1 or 3a where `non_groundtruth_withholding` is `true` — the agent withheld a valid profile it should have submitted.
- **completed_count**: number of tasks where `completed` is `true`.

Incomplete tasks (`completed = false`) are excluded from both the numerator and denominator — they are tracked separately via `completion_rate` and do not count as errors.

## Constraints
An experiment is marked **FAILED** if either of the following conditions is met:
- **Completion rate** falls below 70% — too many tasks did not complete for the results to be reliable.
- **Total cost** exceeds $20 — the run is over budget.

FAILED experiments are still recorded in `data/experiment_results.tsv` but their `status` field will be `FAILED` with a `failed_reason` describing which condition triggered it. Changes from a FAILED run should be reverted.

## Experiment Loop
### Setup (once, before first experiment)
1. Read this file (`program.md`) for full context.
2. Read the in-scope files: `agent_edit.py`, `prepare/other_preps.py`, `prepare/browser_use_submission.py`, `prepare/process_browser_use\_output.py`, `run_experiment.py`.
3. Verify data exists: check that `data/all_samples.json` is present.
4. For each experiment run, the *raw data* from Browser Use and OpanAI processing will be recorded and APPENDED to data/tasks_output.json for reference, with experiment index labelled; all the metrics / measurements will be directly summarized into the file data/experiment_results.tsv 

### Baseline (experiment 0)
Run the current `agent_edit.py` without changes to establish a baseline score.

```bash
python run_experiment.py > run.log 2>&1
```

### Each subsequent experiment
1. **Review history.** Read `data/experiment_results.tsv` to see what has been tried and what the current best score is. Identify what's improved and what goes wrong.
2. **Diagnose.** Read the most recent `run.log` in full. Focus on:
   - Per-type breakdown: which sample types have the highest error rates?
   - Error details: what specific mistakes did the agent make and why?
3. **Hypothesize.** Based on the diagnostics, form a specific hypothesis about what change to `agent_config.py` would improve the score. Write down your hypothesis before making changes.
4. **Edit.** Make focused change to `agent_edit.py`, and write down explanation for why making these changes.
5. **Run.**
   ```bash
   python run_experiment.py > run.log 2>&1
   ```
   Redirect everything. Do NOT use tee or let output flood your context.

6. **Read results.**
   ```bash
   grep "^submission_error_rate:\|^fpr:\|^fnr:\|^completion_rate:\|^run_cost:\|^status:" run.log
   ```

7. **Keep or revert.**
   - In the data/experiment_results.tsv, add a column called `kept`. If `ErrorRate` improved (lower than current best) AND `status` is `OK`: run `git add agent_edit.py && git commit -m "exp N: <tag>"`. Set the `kept` column to `yes`.
   - If `ErrorRate` did not improve OR `status` is `FAILED`: run `git checkout -- agent_config.py`. Update the `kept` column to `no`.

8. After updating to experiment_results.tsv, send an email summary by running:
`python3.11 send_email.py`
Update the subject and body each time to include:
- Experiment number/ git commit id
- Parameter changed with old->new value (LLM, max_steps, or prompt change)
- CompletionRate, ErrorRate, Cost
- Status (PASSED/FAILED)
Example subject: "[pre-auth] Exp 2: LLM gemini-flash->gpt-4o | CompletionRate=85% | ErrorRate=60% | PASSED"

8. **Repeat** from step 1.

## Stopping Criteria
You have a max of 10 total experiments to run (including baseline). Stop after 10 experiments.

## Final Summary
After stopping, write a summary report to stdout:
1. **Best result:** which experiment achieved the lowest `ErrorRate` and what was the score.
2. **What worked:** list the changes that were kept and roughly how much each improved the score.
3. **What didn't work:** list reverted experiments and why they failed.
4. **Remaining failure modes:** which sample types or fields still have the highest error rates.
5. **Recommendations:** what you would try next if given more experiments.