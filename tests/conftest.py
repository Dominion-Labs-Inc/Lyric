"""Tests run against the sandbox store, never the model's.

`torinai_db` is the main model: it holds only what the substrate was taught on
purpose. A test that talks to a real store writes whatever it exercises -- on
2026-09-27 `test_conversation.py` wrote 104 rows into the lesson-only store,
among them the wrong fact `load balancer isa replaced`. So every test process
uses `torinai_dev`, an empty copy of the same structure, unless the run names a
database itself (`POSTGRES_DATABASE=... pytest ...`).

This holds because the one authority for connection settings
(`core/database/postgres_config.py`) puts the process environment ahead of the
`.env` files, and the `.env.production` that several tests load with
`override=True` sets no `POSTGRES_*` value.
"""
import os

os.environ.setdefault("POSTGRES_DATABASE", "torinai_dev")
