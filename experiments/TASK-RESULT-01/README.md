# TASK-RESULT-01 — fetching a job's result, scoped to who asked

**What it tests.** A job request enters through the front door, is queued as a task scoped to the
person who asked, and returns a task ID straight away. This experiment checks the other half,
getting the result back:
- submitting returns a task ID and a handle to poll, and the task belongs to the requester, not
  the substrate;
- polling before the job finishes reports that it is still working;
- once it finishes, polling returns the result, both directly and through the front door
  (`metadata={"task_result": id}`);
- a failed job reports that it failed, and why;
- another user polling the same ID gets `not_found`.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/TASK-RESULT-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
