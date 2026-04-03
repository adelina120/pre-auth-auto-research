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

If `completion_rate` drops below 0.7, the run is automatically rejected (scored as 999). Do not write prompts that cause excessive browser steps, retries, or navigation complexity.

## Constraints
- **Completion**: if the completion rate is
- **Per-run limit: $50.** Enforced automatically by `run_experiment.py`. Over-budget runs receive `submission_error_rate: 999` and are always reverted. Avoid changes that inflate token count or browser step count. A typical successful run costs $25–35.
- **Total experiment limit: 10 runs** (including baseline). After experiment 10, stop and write a summary.
- **Cumulative budget** is tracked in `results.tsv`. If remaining budget cannot cover a worst-case $50 run, `run_experiment.py` will block the experiment from starting.

Write efficient prompts. The browser agent does not need elaborate multi-step verification or retry loops to perform well.

## Experiment Loop

### Setup (once, before first experiment)

1. Read this file (`program.md`) for full context.
2. Read the in-scope files: `agent_config.py`, `prepare.py`, `run_experiment.py`, `make_submissions.py`.
3. Verify data exists: check that `data/generated/groundtruth.json` and `data/generated/eval_set.json` are present.
4. If `results.tsv` does not exist, create it with the header row only.

### Baseline (experiment 0)

Run the current `agent_config.py` without changes to establish a baseline score.

```bash
python run_experiment.py > run.log 2>&1
```

Read the results and record them as experiment 0 in `results.tsv`.

### Each subsequent experiment

1. **Review history.** Read `results.tsv` to see what has been tried and what the current best score is.
2. **Diagnose.** Read the most recent `run.log` in full. Focus on:
   - Per-type breakdown: which sample types have the highest error rates?
   - Error details: what specific mistakes did the agent make and why?
   - Per-field accuracy: which form fields are filled incorrectly?
   - Cost: is the run near the $50 limit?
3. **Hypothesize.** Based on the diagnostics, form a specific hypothesis about what change to `agent_config.py` would improve the score. Write down your hypothesis before making changes.
4. **Edit.** Make a focused change to `agent_config.py`. Change one thing at a time when possible — it makes the signal clearer. Large multi-variable changes make it hard to attribute improvement or regression.
5. **Run.**
   ```bash
   python run_experiment.py > run.log 2>&1
   ```
   Redirect everything. Do NOT use tee or let output flood your context.
6. **Read results.**
   ```bash
   grep "^submission_error_rate:\|^fpr:\|^fnr:\|^completion_rate:\|^run_cost:\|^status:" run.log
   ```
   If grep output is empty, the run crashed. Run `tail -n 50 run.log` for the stack trace and attempt a fix. If you cannot resolve it after a few attempts, revert and try a different approach.
7. **Record.** Append the result to `results.tsv` with all columns filled except `kept`.
8. **Keep or revert.**
   - If `submission_error_rate` improved (lower than current best) AND `status` is `OK`: run `git add agent_config.py && git commit -m "exp N: <tag>"`. Update the `kept` column to `yes`.
   - If `submission_error_rate` did not improve OR `status` is `REJECTED`: run `git checkout -- agent_config.py`. Update the `kept` column to `no`.
9. **Repeat** from step 1.

### results.tsv Format

```
exp	tag	submission_error_rate	fpr	fnr	completion_rate	cost	status	kept
0	baseline	0.38	0.25	0.40	0.92	32.10	OK	yes
```

Do NOT commit `results.tsv` to git. Leave it untracked so that git resets do not erase experiment history.

## Known Failure Modes from Prior Experiments

The following patterns were identified from 700 prior runs across 3 LLMs. Use them to prioritize your experiments.

### Decision Errors

- **Type 4 (colliding names)** is the hardest. Agents frequently submit without noticing the name collision. The duplicate name often appears in a separate profile within the same batch, and agents fail to cross-reference.
- **Type 2a (subscriber age)** is commonly missed. Agents accept the subscriber information at face value without computing the age difference. Explicit instructions to calculate and verify the age gap help.
- **Type 2b (date ordering)** is sometimes caught, sometimes missed. Agents that are instructed to explicitly compare dates before submitting perform better.
- **Type 2c (missing collection date)** is the easiest "stop" type. Most agents catch the missing required field.
- **Type 3b (irrelevant clinical info)** is caught by most agents, but some over-index on the presence of medical terminology and submit anyway.
- **Types 1 and 3a (valid, should submit)** sometimes trigger false negatives. Agents that are overly cautious about stop criteria refuse to submit legitimate profiles. This is especially common when the prompt has very aggressive withholding instructions.

## Stopping Criteria

Stop when ANY of these conditions is met:
1. You have run 10 total experiments (including baseline).
2. Five consecutive experiments produced no improvement.
3. `submission_error_rate` drops below 0.05.
4. Cumulative cost makes it impossible to start another run.

## Final Summary

After stopping, write a summary report to stdout:
1. **Best result:** which experiment achieved the lowest `submission_error_rate` and what was the score.
2. **What worked:** list the changes that were kept and roughly how much each improved the score.
3. **What didn't work:** list reverted experiments and why they failed.
4. **Remaining failure modes:** which sample types or fields still have the highest error rates.
5. **Recommendations:** what you would try next if given more experiments.