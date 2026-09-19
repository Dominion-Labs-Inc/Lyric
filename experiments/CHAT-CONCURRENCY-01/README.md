# CHAT-CONCURRENCY-01 — how many people can chat at once

**What it tests.** It teaches the shared mind a short chain of facts, then sends N simultaneous
questions from N different users through the real front door (`handle_user_request`), with N rising
each round. It measures wall time, throughput, latency per request, error rate, and whether the answers
are right. This is chat capacity, separate from the cap on concurrent work jobs.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/CHAT-CONCURRENCY-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
