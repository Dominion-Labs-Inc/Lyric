# kite17_ablation — run 2026-08-17T20:26:24.877133+00:00

**Hypothesis.** The novel capability is causally carried by unified.learned_rules. Removing that learned state removes the capability; restoring the same state restores it, with source code, runtime, evaluation inputs and model availability unchanged.

Each condition runs the same frozen case suite against its own copy of the database (source: `torinai_db`), with the model off and learning frozen.

| Condition | Database connected | Rules executable | Cases passed |
|---|---|---|---|
| FULL | torinai_abl_full | 2 | 14/14 |
| SHAM | torinai_abl_sham | 2 | 14/14 |
| NO_LEARNED_RULES | torinai_abl_no_learned_rules | 0 | 7/14 |
| RULE_PRESENT_BUT_NOT_VALIDATED | torinai_abl_rule_present_but_not_validated | 0 | 7/14 |
| NO_CONCEPTS | torinai_abl_no_concepts | 2 | 14/14 |
| BLANK | torinai_abl_blank | 0 | 7/14 |
| RESTORED | torinai_abl_restored | 2 | 14/14 |

Commit: not_a_git_repo. Frozen rules: rule_d3244fd036c3, rule_dcd916b30f7f.

Generated from `kite17_ablation.json`, the data for this run.
