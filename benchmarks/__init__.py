"""TorinAI capability benchmarks.

The substrate is not an LLM. To know whether its faculties actually beat a
language model at a task — and to keep collecting that evidence across many
sessions as the substrate grows — each benchmark pits the substrate against a
bare local LLM on the SAME tasks, in the SAME world, judged by the SAME
independent oracle.

The LLM baseline uses NOTHING of the substrate except the tools (the shared
filesystem world). No belief, no re-observation, no completion authority behind
it — a model with tools, which is the honest thing to compare a model-free
substrate against.

Suites:
  completion_honesty — does the agent know, truthfully, when a task is actually
  done? (the first suite; the completion-belief arc under test)
"""
