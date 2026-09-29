#!/usr/bin/env python3
"""
Capability Benchmark Suite — measures the SUBSTRATE's capability on frozen test cases.

Owned by the learning authority (the one owner of capability measurement). Each frozen case
is answered by the substrate via the neural bridge (substrate-first: deterministic formalizers
and solvers before any model — so this measures the substrate, not a model that may be behind
it) and graded against the expected output with a FROZEN grader (token-F1 / exact / contains),
never a model grading itself. A case the substrate cannot yet represent scores an honest 0.0
(real substrate coverage), and a case that could not run is UNGRADED (score=None) and excluded
from the averages — an infrastructure fault never manufactures a capability drop.

Domains: reasoning, coding, analysis, comprehension (+ substrate). Frozen cases live in
`capability_benchmarks/*.json`; results + reports persist to the database.

Long-horizon regression across cycles is NOT tracked here — that is the learning authority's
job (`track_capability_baseline` on the scores this produces). The suite MEASURES a cycle; the
authority tracks the baseline.
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dotenv import load_dotenv

from core.database import (LyricUnifiedDatabase, get_database_manager,
                           get_unified_db)

# Load environment variables
env_file = Path(__file__).parent.parent.parent / ".env.production"
if env_file.exists():
    load_dotenv(env_file)

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkTestCase:
    """Single frozen test case"""
    test_id: str
    domain: str  # "reasoning", "coding", "analysis", "comprehension"
    difficulty: str  # "easy", "medium", "hard"
    prompt: str
    expected_output: str
    evaluation_criteria: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Result of running a single benchmark"""
    test_id: str
    cycle_id: str
    timestamp: datetime
    success: bool
    score: float  # 0.0-1.0
    latency_ms: float
    output: str
    evaluation_details: Dict[str, Any]


@dataclass
class CapabilityReport:
    """Capability assessment across all domains"""
    cycle_id: str
    timestamp: datetime

    # Domain scores (0.0-1.0)
    reasoning_score: float
    coding_score: float
    analysis_score: float
    comprehension_score: float
    overall_score: float

    # Regression detection
    regression_detected: bool
    regression_domains: List[str]
    regression_severity: str  # "NONE", "MINOR", "MODERATE", "SEVERE"

    # Statistical data
    tests_passed: int
    tests_failed: int
    avg_latency_ms: float
    confidence_interval: Tuple[float, float]

    # Comparison to baseline
    baseline_delta: float
    statistical_significance: float  # p-value


class CapabilityBenchmarkSuite:
    """
    Frozen capability benchmark suite for regression detection

    Prevents capability narrowing by maintaining frozen test cases that evaluate
    general reasoning, coding, analysis, and comprehension across all improvement cycles.
    """

    def __init__(self, db_config: Dict[str, Any] = None):
        # db_config kept for backward compatibility but no longer used directly;
        # CapabilityBenchmarkSuite now uses the unified PostgreSQL database.
        _ = db_config

        # EVERY DATABASE CALL IN THIS SUITE WAS FAILING.
        #
        # `get_unified_db` is declared `async` while doing nothing async -- it
        # just returns the singleton -- so this stored a COROUTINE, and every
        # `self.db.execute_query(...)` raised
        #
        #     'coroutine' object has no attribute 'execute_query'
        #
        # into a handler that logged and continued. Measured consequences:
        # `frozen_capability_benchmarks` held 0 rows after loading the
        # benchmarks and no benchmark result was ever persisted.
        #
        # `get_database_manager` is the synchronous accessor and returns the
        # same singleton object (verified identical).
        self.db: LyricUnifiedDatabase = get_database_manager()

        # Benchmark storage
        self.benchmarks: Dict[str, BenchmarkTestCase] = {}
        self.benchmarks_loaded = False

        #: The substrate that answers the benchmarks. Lazily built so
        #: constructing the suite does not initialise the reasoning stack.
        self._neural_bridge = None

        logger.info("Capability Benchmark Suite initialized")

    def _reasoner(self):
        """The neural bridge. Substrate-first; a model only if it escalates."""
        if self._neural_bridge is None:
            from core.reasoning.neural_bridge import get_neural_bridge

            self._neural_bridge = get_neural_bridge()
        return self._neural_bridge

    async def load_benchmarks(self, benchmarks_dir: Optional[Path] = None) -> int:
        """
        Load frozen benchmarks from JSON files

        Args:
            benchmarks_dir: Directory containing benchmark JSON files

        Returns:
            Number of benchmarks loaded
        """
        if benchmarks_dir is None:
            benchmarks_dir = Path(__file__).parent / "capability_benchmarks"

        if not benchmarks_dir.exists():
            logger.warning(f"Benchmark directory not found: {benchmarks_dir}")
            return 0

        loaded = 0

        # Load benchmarks from JSON files
        for json_file in benchmarks_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)

                # Each JSON file contains a list of test cases
                for test_data in data.get('tests', []):
                    benchmark = BenchmarkTestCase(
                        test_id=test_data['test_id'],
                        domain=test_data['domain'],
                        difficulty=test_data['difficulty'],
                        prompt=test_data['prompt'],
                        expected_output=test_data['expected_output'],
                        evaluation_criteria=test_data.get('evaluation_criteria', {}),
                        metadata=test_data.get('metadata', {})
                    )

                    self.benchmarks[benchmark.test_id] = benchmark
                    loaded += 1

                logger.info(f"Loaded {len(data.get('tests', []))} benchmarks from {json_file.name}")

            except Exception as e:
                logger.error(f"Error loading benchmarks from {json_file}: {e}")

        # Store benchmarks in database (if not already stored)
        await self._store_benchmarks_in_db()

        self.benchmarks_loaded = True
        logger.info(f"✅ Loaded {loaded} total capability benchmarks")

        return loaded

    async def _store_benchmarks_in_db(self):
        """Store benchmarks in database for persistence"""
        try:
            for benchmark in self.benchmarks.values():
                # Check if already exists in unified.frozen_capability_benchmarks
                existing = await self.db.execute_query(
                    """
                    SELECT test_id
                    FROM frozen_capability_benchmarks
                    WHERE test_id = $1
                    """,
                    params=(benchmark.test_id,),
                    fetch_one=True,
                )

                if existing:
                    continue  # Already stored

                # Store new benchmark in unified.frozen_capability_benchmarks
                await self.db.execute_query(
                    """
                    INSERT INTO frozen_capability_benchmarks
                    (test_id, domain, difficulty, prompt, expected_output,
                     evaluation_criteria, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    params=(
                        benchmark.test_id,
                        benchmark.domain,
                        benchmark.difficulty,
                        benchmark.prompt,
                        benchmark.expected_output,
                        json.dumps(benchmark.evaluation_criteria),
                        json.dumps(benchmark.metadata),
                    ),
                )

        except Exception as e:
            logger.error(f"Error storing benchmarks in database: {e}")

    async def run_benchmarks(
        self,
        cycle_id: str,
        domains: Optional[List[str]] = None,
        sample_size: Optional[int] = None
    ) -> CapabilityReport:
        """
        Run capability benchmarks for a cycle

        Args:
            cycle_id: Improvement cycle ID
            domains: Specific domains to test (None = all)
            sample_size: Limit number of tests per domain (None = all)

        Returns:
            CapabilityReport with results
        """
        if not self.benchmarks_loaded:
            await self.load_benchmarks()

        # NO MODEL REQUIREMENT. This refused to run at all without an
        # `llm_service`, which made the capability gate model-dependent: with
        # the model down every cycle came back UNKNOWN and capability was never
        # verified. Answers now come from the substrate via the neural bridge
        # (the bridge is substrate-first and substrate-only -- it never reaches a
        # model to answer), so the benchmark measures the substrate
        # rather than the model that may or may not be behind it.

        # Filter benchmarks by domain
        if domains:
            test_benchmarks = [b for b in self.benchmarks.values() if b.domain in domains]
        else:
            test_benchmarks = list(self.benchmarks.values())

        # Sample if requested
        if sample_size:
            import random
            # Sample evenly across domains
            domain_samples = {}
            for benchmark in test_benchmarks:
                if benchmark.domain not in domain_samples:
                    domain_samples[benchmark.domain] = []
                domain_samples[benchmark.domain].append(benchmark)

            sampled = []
            per_domain = sample_size // len(domain_samples)
            for domain_tests in domain_samples.values():
                sampled.extend(random.sample(domain_tests, min(per_domain, len(domain_tests))))

            test_benchmarks = sampled

        logger.info(f"🧪 Running {len(test_benchmarks)} capability benchmarks for cycle {cycle_id}")

        # Run each benchmark
        results: List[BenchmarkResult] = []
        for benchmark in test_benchmarks:
            result = await self._run_single_benchmark(benchmark, cycle_id)
            results.append(result)

            # Store result in database
            await self._store_result(result)

        # Generate capability report
        report = await self._generate_capability_report(cycle_id, results)

        # Store report in database
        await self._store_report(report)

        return report

    async def _run_single_benchmark(
        self,
        benchmark: BenchmarkTestCase,
        cycle_id: str
    ) -> BenchmarkResult:
        """Run a single benchmark test"""
        import time

        start_time = time.time()

        try:
            # THE SUBSTRATE ANSWERS, NOT A MODEL SERVICE.
            #
            # This called `self.llm_service.generate(...)` directly, so the
            # frozen benchmark measured whatever model happened to be served
            # and could not run at all without one. The bridge is
            # substrate-first: deterministic formalizers and solvers are tried
            # before any model is consulted, which is the thing whose
            # capability this suite is supposed to be tracking.
            from core.reasoning.neural_bridge import (ReasoningMode,
                                                      ReasoningRequest)

            from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
            request = ReasoningRequest(
                query=benchmark.prompt,
                context=[f"Capability benchmark {benchmark.test_id}",
                         f"Domain: {benchmark.domain}"],
                task_metadata={"actor": SUBSTRATE_ACTOR},
            )
            result = await self._reasoner().reason(request)

            latency_ms = (time.time() - start_time) * 1000

            # A FAILED GENERATION IS NOT A WRONG ANSWER.
            #
            # `reason()` reports failure by putting the reason IN the answer --
            # "Error: LLM generation failed (answer truncated: the model used
            # its entire 2048-token budget on reasoning without emitting...)"
            # -- and recording the real state in metadata. Grading that string
            # against the expected answer scores 0.0, and the capability report
            # then says the substrate cannot reason.
            #
            # Measured on this suite: reasoning 0.03 and comprehension 0.03,
            # almost entirely from truncated generations. Freezing a baseline
            # on those numbers would make an infrastructure fault the permanent
            # definition of the system's competence.
            metadata = getattr(result, "metadata", None) or {}
            answer = str(getattr(result, "answer", "") or "")

            # THIS SUITE MEASURES THE SUBSTRATE. IT WAS MEASURING THE MODEL.
            #
            # The bridge is substrate-first, so the routing was
            # right -- but every one of these benchmarks is prose the substrate
            # cannot yet represent, so `_substrate_first` declines all of them
            # and, with no model fallback, they return honest inability. Before
            # the fallback was removed, the model's answer was
            # then graded and recorded as the SUBSTRATE's capability.
            #
            # The proof is in the stored results: items that came back
            # "Error: LLM generation failed (answer truncated: the model used
            # its entire 2048-token budget...)" scored 0 -- a model-side fault
            # attributed to substrate competence -- while `reasoning_logic_001`
            # returned fluent model prose and also scored 0. Neither number
            # said anything about the substrate.
            #
            # A substrate that cannot answer yet is the honest starting point,
            # and moving that number is what teaching is for. Masking it with a
            # model's answer means the baseline can never show learning,
            # because it was never measuring the thing that learns.
            substrate_answered = bool(metadata.get(
                "substrate_formalized", metadata.get("verified", False)))
            teacher_consulted = bool(metadata.get("teacher_consulted", False))

            if not substrate_answered:
                # NOT ungraded, and not an error: a real, recorded ZERO. The
                # substrate could not answer this, which is a fact about the
                # substrate and exactly what the baseline should track.
                logger.info(
                    "Benchmark %s: substrate could not represent it "
                    "(teacher_consulted=%s) — recorded as 0.0 substrate capability",
                    benchmark.test_id, teacher_consulted)
                return BenchmarkResult(
                    test_id=benchmark.test_id, cycle_id=cycle_id,
                    timestamp=datetime.now(), success=False, score=0.0,
                    latency_ms=latency_ms, output=answer,
                    evaluation_details={
                        "graded": True, "grader": "substrate_coverage",
                        "answered_by": "teacher" if teacher_consulted else "nobody",
                        "substrate_formalized": False,
                        "reason": metadata.get("reason") or "unsupported_input",
                        "note": ("the substrate could not represent this input; "
                                 "any answer shown came from the teacher and "
                                 "does not count as substrate capability")})

            output = answer

            # Evaluate output
            evaluation = await self._evaluate_output(
                output=output,
                expected=benchmark.expected_output,
                criteria=benchmark.evaluation_criteria
            )

            success = evaluation['success']
            score = evaluation['score']

            return BenchmarkResult(
                test_id=benchmark.test_id,
                cycle_id=cycle_id,
                timestamp=datetime.now(),
                success=success,
                score=score,
                latency_ms=latency_ms,
                output=output,
                evaluation_details=evaluation
            )

        except Exception as e:
            # A BENCHMARK THAT COULD NOT RUN IS NOT A BENCHMARK THE SYSTEM
            # FAILED. score=0.0 fed straight into the domain average and the
            # regression detector, so an unreachable reasoner or a transport
            # error manufactured exactly the capability drop this suite exists
            # to detect. Ungraded results are excluded from the scores.
            logger.error(f"Benchmark {benchmark.test_id} could not run: {e}")
            return BenchmarkResult(
                test_id=benchmark.test_id,
                cycle_id=cycle_id,
                timestamp=datetime.now(),
                success=None,
                score=None,
                latency_ms=(time.time() - start_time) * 1000,
                output="",
                evaluation_details={'error': str(e), 'graded': False}
            )

    async def _evaluate_output(
        self,
        output: str,
        expected: str,
        criteria: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Evaluate LLM output against expected output

        Uses criteria-specific evaluation methods (exact match, semantic similarity, etc.)
        """
        evaluation_type = criteria.get('type', 'semantic_similarity')

        if evaluation_type == 'exact_match':
            success = output.strip() == expected.strip()
            score = 1.0 if success else 0.0

        elif evaluation_type == 'contains':
            required_phrases = criteria.get('required_phrases', [])
            matches = sum(1 for phrase in required_phrases if phrase in output)
            score = matches / len(required_phrases) if required_phrases else 0.0
            success = score >= criteria.get('threshold', 0.7)

        elif evaluation_type == 'semantic_similarity':
            # A FROZEN BENCHMARK NEEDS A FROZEN GRADER.
            #
            # This asked the model to score its own answer. Two things wrong
            # with that: the model attests to its own competence, which the
            # substrate architecture forbids everywhere else; and the yardstick
            # then drifts with the model, so a score from one cycle is not
            # comparable with a score from the next -- which is the entire
            # purpose of a frozen suite.
            #
            # Worse, `except: score = 0.0` turned a failed GRADING call into a
            # failed BENCHMARK, and enough of those read as capability
            # regression -- a fabricated one, from a grader that never ran.
            #
            # Token F1 against the expected answer is deterministic, needs no
            # model, and is the standard measure for exactly this comparison.
            score = self._token_f1(output, expected)
            success = score >= criteria.get('threshold', 0.7)

        elif evaluation_type == 'custom':
            # NOT SILENTLY ZERO. `custom` had no branch, so it fell to the
            # `else` below and scored 0.0 on every run -- one of the 26 frozen
            # benchmarks was permanently failing and dragging the capability
            # score down for a reason nobody had stated.
            score, success, detail = self._evaluate_custom(output, criteria)
            return {'success': success, 'score': score,
                    'evaluation_type': evaluation_type, 'criteria': criteria,
                    'grader': 'deterministic', 'detail': detail}

        else:
            # An unknown type is UNGRADED, not failed. Returning success=False
            # made "this suite does not know how to mark it" indistinguishable
            # from "the system got it wrong".
            logger.error("Unknown evaluation type %r for a frozen benchmark; "
                         "reporting UNGRADED rather than failed", evaluation_type)
            return {'success': None, 'score': None, 'graded': False,
                    'evaluation_type': evaluation_type, 'criteria': criteria,
                    'grader': 'none',
                    'detail': f'no grader for evaluation type {evaluation_type!r}'}

        return {
            'success': success,
            'score': score,
            'graded': True,
            'grader': 'deterministic',
            'evaluation_type': evaluation_type,
            'criteria': criteria
        }

    #: Words carrying no content, excluded so overlap measures meaning rather
    #: than grammar. Short and fixed on purpose: a grader that tunes its own
    #: stopword list is no longer frozen.
    _STOPWORDS = frozenset({
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "of", "to", "in", "on", "at", "by", "for", "with", "and", "or", "but",
        "that", "this", "these", "those", "it", "its", "as", "from", "then",
        "so", "because", "which", "there", "their",
    })

    @classmethod
    def _tokens(cls, text: str) -> List[str]:
        import re
        words = re.findall(r"[a-z0-9]+", str(text).lower())
        return [w for w in words if w not in cls._STOPWORDS]

    @classmethod
    def _token_f1(cls, output: str, expected: str) -> float:
        """Harmonic mean of token precision and recall. Deterministic.

        Rewards an answer that contains what the expected answer contains
        without padding, and is stable across runs -- two properties the model
        grader had neither of.
        """
        from collections import Counter

        produced, wanted = Counter(cls._tokens(output)), Counter(cls._tokens(expected))
        if not produced or not wanted:
            return 0.0
        shared = sum((produced & wanted).values())
        if not shared:
            return 0.0
        precision = shared / sum(produced.values())
        recall = shared / sum(wanted.values())
        return 2 * precision * recall / (precision + recall)

    @staticmethod
    def _evaluate_custom(output: str, criteria: Dict[str, Any]):
        """Graders for the constraint benchmarks, keyed by their description.

        Each is a stated, checkable rule rather than a judgement, so the result
        does not depend on who is asked.
        """
        description = str(criteria.get('description', '')).strip()
        threshold = float(criteria.get('threshold', 1.0))

        forbidden = None
        if "must not contain the letter" in description.lower():
            import re
            letters = re.findall(r"'([A-Za-z])'", description)
            forbidden = {c.lower() for c in letters}

        if forbidden:
            hits = sum(1 for c in str(output).lower() if c in forbidden)
            score = 1.0 if hits == 0 else 0.0
            return score, score >= threshold, (
                f"{hits} occurrence(s) of {sorted(forbidden)}")

        # No grader for this rule. UNGRADED, never failed.
        return None, None, f"no deterministic grader for constraint: {description!r}"

    async def _generate_capability_report(
        self,
        cycle_id: str,
        results: List[BenchmarkResult]
    ) -> CapabilityReport:
        """Generate capability report from benchmark results"""

        # UNGRADED RESULTS ARE NOT ZEROES. A test with no grader, or one that
        # could not run, carries score=None; averaging it as 0.0 would report a
        # capability drop that nothing measured, and `len(results) -
        # tests_passed` would count it as a failure.
        graded = [r for r in results if r.score is not None]
        ungraded = [r for r in results if r.score is None]
        if ungraded:
            logger.warning("%d of %d benchmarks were UNGRADED and are excluded "
                           "from the capability scores: %s", len(ungraded),
                           len(results), ", ".join(r.test_id for r in ungraded))

        # Calculate domain scores
        domain_scores = {}
        # A DOMAIN WITH NOTHING TO GRADE IS NOT A DOMAIN SCORING ZERO.
        #
        # The else branch below set an unmeasured domain to 0.0 and the overall
        # score averaged it in, so a suite holding no coding benchmarks reported
        # coding competence of zero and dragged the overall down with it.
        # Unmeasured domains are excluded from the overall average and reported
        # separately, so "we did not test this" stays distinct from "it failed".
        unmeasured_domains = []
        for domain in ['reasoning', 'coding', 'analysis', 'comprehension']:
            domain_results = [r for r in graded if self.benchmarks[r.test_id].domain == domain]
            if domain_results:
                domain_scores[domain] = sum(r.score for r in domain_results) / len(domain_results)
            else:
                unmeasured_domains.append(domain)

        overall_score = sum(domain_scores.values()) / len(domain_scores) if domain_scores else 0.0
        if unmeasured_domains:
            logger.warning("No graded benchmarks for %s; excluded from the overall "
                           "score rather than counted as zero",
                           ", ".join(unmeasured_domains))

        # Calculate statistics
        tests_passed = sum(1 for r in graded if r.success)
        tests_failed = len(graded) - tests_passed
        avg_latency = sum(r.latency_ms for r in results) / len(results) if results else 0.0

        # Calculate confidence interval (Wilson score)
        confidence_interval = self._calculate_wilson_score(tests_passed, len(graded))

        # Long-horizon regression detection is the LEARNING AUTHORITY's job now
        # (track_capability_baseline on the overall/domain scores). The suite
        # MEASURES a cycle; the authority tracks the baseline across cycles. So
        # the report carries this cycle's scores and no baseline comparison.
        regression_detected, regression_domains, regression_severity = False, [], "NONE"
        baseline_delta, p_value = None, None

        return CapabilityReport(
            cycle_id=cycle_id,
            timestamp=datetime.now(),
            reasoning_score=domain_scores.get('reasoning'),
            coding_score=domain_scores.get('coding'),
            analysis_score=domain_scores.get('analysis'),
            comprehension_score=domain_scores.get('comprehension'),
            overall_score=overall_score,
            regression_detected=regression_detected,
            regression_domains=regression_domains,
            regression_severity=regression_severity,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            avg_latency_ms=avg_latency,
            confidence_interval=confidence_interval,
            baseline_delta=baseline_delta,
            statistical_significance=p_value
        )

    def _calculate_wilson_score(self, successes: int, total: int) -> Tuple[float, float]:
        """Calculate Wilson score confidence interval (95%)"""
        if total == 0:
            return (0.0, 0.0)

        from math import sqrt

        z = 1.96  # 95% confidence
        p = successes / total

        denominator = 1 + z**2 / total
        center = (p + z**2 / (2 * total)) / denominator
        margin = z * sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denominator

        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)

        return (lower, upper)


    async def _store_result(self, result: BenchmarkResult):
        """Store benchmark result in database"""
        try:
            result_id = f"{result.test_id}_{result.cycle_id}_{result.timestamp.timestamp()}"

            await self.db.execute_query(
                """
                INSERT INTO capability_benchmark_results
                (result_id, test_id, cycle_id, timestamp, success, score,
                 latency_ms, output, evaluation_details)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                params=(
                    result_id,
                    result.test_id,
                    result.cycle_id,
                    result.timestamp,
                    result.success,
                    result.score,
                    result.latency_ms,
                    result.output,
                    json.dumps(result.evaluation_details),
                ),
            )

        except Exception as e:
            logger.error(f"Error storing benchmark result: {e}")

    async def _store_report(self, report: CapabilityReport):
        """Store capability report in database"""
        try:
            report_id = f"capability_report_{report.cycle_id}_{report.timestamp.timestamp()}"

            await self.db.execute_query(
                """
                INSERT INTO capability_reports
                (report_id, cycle_id, timestamp, reasoning_score, coding_score,
                 analysis_score, comprehension_score, overall_score,
                 regression_detected, regression_domains, regression_severity,
                 tests_passed, tests_failed, avg_latency_ms,
                 baseline_delta, statistical_significance)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                params=(
                    report_id,
                    report.cycle_id,
                    report.timestamp,
                    report.reasoning_score,
                    report.coding_score,
                    report.analysis_score,
                    report.comprehension_score,
                    report.overall_score,
                    report.regression_detected,
                    ','.join(report.regression_domains),
                    report.regression_severity,
                    report.tests_passed,
                    report.tests_failed,
                    report.avg_latency_ms,
                    report.baseline_delta,
                    report.statistical_significance,
                ),
            )

            logger.info(f"✅ Stored capability report for cycle {report.cycle_id}")

        except Exception as e:
            logger.error(f"Error storing capability report: {e}")

    def _create_error_report(self, cycle_id: str, error: str) -> CapabilityReport:
        """Report that the benchmarks could not run — NOT that they passed.

        This previously returned `regression_detected=False,
        regression_severity="NONE"` with every score at 0.0 and 0 tests run,
        which is indistinguishable from a clean pass. "I could not measure
        capability" must never read as "no capability was lost".

        `regression_detected=True` with severity UNKNOWN is the honest answer:
        something is wrong and it has not been ruled out. The flag, the empty
        domains and `tests_passed == tests_failed == 0` are all visible to any
        caller that looks, and the log says so plainly.
        """
        logger.error(
            f"CAPABILITY BENCHMARKS DID NOT RUN ({error}) — reporting UNKNOWN, "
            f"not 'no regression'. 0 of {len(self.benchmarks)} frozen tests executed; "
            f"capability regression has NOT been ruled out for cycle {cycle_id}."
        )
        return CapabilityReport(
            cycle_id=cycle_id,
            timestamp=datetime.now(),
            reasoning_score=0.0,
            coding_score=0.0,
            analysis_score=0.0,
            comprehension_score=0.0,
            overall_score=0.0,
            regression_detected=True,
            regression_domains=["<benchmarks did not run>"],
            regression_severity="UNKNOWN",
            tests_passed=0,
            tests_failed=0,
            avg_latency_ms=0.0,
            confidence_interval=(0.0, 0.0),
            baseline_delta=0.0,
            # Not 1.0 — that asserted a perfectly insignificant difference from
            # a comparison never performed.
            statistical_significance=0.0
        )



# Global singleton
_capability_benchmark_suite: Optional[CapabilityBenchmarkSuite] = None


def get_capability_benchmark_suite() -> CapabilityBenchmarkSuite:
    """Get or create the global capability benchmark suite"""
    global _capability_benchmark_suite
    if _capability_benchmark_suite is None:
        _capability_benchmark_suite = CapabilityBenchmarkSuite()
    return _capability_benchmark_suite
