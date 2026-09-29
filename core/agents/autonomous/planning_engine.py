#!/usr/bin/env python3
"""
Planning Engine - Simplified goal and task planning
Consolidates all planning functionality from the monolithic controller
"""

from core.capability import raise_if_structural
import asyncio
import json
import re
import logging
from enum import Enum
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from uuid import uuid4

from .shared_types import (
    Goal, GoalType, Task, Plan, TaskType, TaskStatus, Priority, SystemState,
    PRIORITY_ORDINAL, priority_from_ordinal,
)
from .execution_plan_adapter import state_plan_to_tasks
from core.reasoning.temporal_reasoning import PlanningStatus


class PlanInput(Enum):
    """What a KIND of plan needs before it can be formed.

    Not every plan is the same. A state goal needs the world as it is now and the
    operators the substrate has learned; a descriptive one needs what its tools
    have actually done and what the substrate abstracted from past experience.
    Declaring that per kind makes the difference stated rather than implied, and
    each input is obtained through the AUTHORITY that owns it — never by reaching
    into a store behind its owner's back.
    """
    #: The world as it is now. The COORDINATOR perceives; the planner is given it.
    OBSERVED_WORLD = "observed_world"
    #: The operators the substrate has learned — the rule store.
    LEARNED_OPERATORS = "learned_operators"
    #: How the tools have actually performed — the learning authority.
    TOOL_HISTORY = "tool_history"
    #: Principles and schemas — the reasoning authority, which owns abstraction.
    ABSTRACTION = "abstraction"
    #: Specific past experiences, queried within the abstraction's constraints.
    #: Named for what the memory authority calls it — `MemoryType.EPISODIC` —
    #: rather than a term invented here.
    EPISODIC_MEMORY = "episodic_memory"
    #: Earned correctness in a domain — the domain authority.
    OPERATING_RELIABILITY = "operating_reliability"


#: What each kind of plan declares it needs. The engine assembles exactly this.
PLAN_KIND_INPUTS: Dict[str, Tuple[PlanInput, ...]] = {
    "state": (PlanInput.OBSERVED_WORLD, PlanInput.LEARNED_OPERATORS,
              PlanInput.OPERATING_RELIABILITY),
    "template": (PlanInput.TOOL_HISTORY, PlanInput.ABSTRACTION,
                 PlanInput.EPISODIC_MEMORY),
}


@dataclass
class PlanningOutcome:
    """What planning established, and by which mode.

    Returned instead of `Plan | None` so a caller can tell UNREACHABLE (proved
    impossible) from INDETERMINATE (not established) from UNSUPPORTED_GOAL.
    Collapsing those into None is what let the absence of a plan look like an
    ordinary result for the lifetime of this module.
    """

    status: PlanningStatus
    plan: Optional[Plan] = None
    planning_mode: str = "template"
    reason: str = ""
    goal_conditions: List[str] = field(default_factory=list)
    grounding_complete: bool = True
    operators_considered: int = 0

    @property
    def found(self) -> bool:
        return self.status is PlanningStatus.PLAN_FOUND
from core.database import get_unified_db
from core.tools import get_tool_registry, ToolRegistry

logger = logging.getLogger(__name__)


class PlanningEngine:
    """Manages goal setting, task planning, and execution sequencing"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False

        # Planning state
        self.current_goals: Dict[str, Goal] = {}
        self.active_plans: Dict[str, Plan] = {}
        self.task_queue: Dict[str, Task] = {}

        # Tool system integration
        self.tool_registry: ToolRegistry = get_tool_registry()

        # Use unified database singleton - initialized in async initialize()
        self.unified_db = None
        self.connection = None  # For backwards compatibility

        # Planning constraints
        self.max_concurrent_tasks = self.config.get("max_concurrent_tasks", 5)
        self.planning_horizon = self.config.get("planning_horizon_hours", 24)

        # Statistics
        self.stats = {
            "goals_created": 0,
            "plans_generated": 0,
            "tasks_completed": 0,
            "success_rate": 0.0,
            "tools_planned": 0
        }
    
    async def initialize(self) -> bool:
        """Initialize the planning engine"""
        try:
            # Get unified database singleton
            self.unified_db = await get_unified_db()
            # get_unified_db explicitly does NOT initialize the pool; main.py
            # does it at startup. Any other entry point reached this line with an
            # uninitialized pool, and every persistence call below then failed
            # into a logger.error while initialize() still returned True.
            if not getattr(self.unified_db, "initialized", False):
                await self.unified_db.initialize()

            # LyricUnifiedDatabase uses connection pools, not direct connection
            self.connection = self.unified_db  # Store database instance for queries

            # Create tables in unified PostgreSQL database
            await self._create_tables()

            # Load existing goals and plans
            await self._load_persistent_state()
            
            self.active = True
            logger.info("Planning engine initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize planning engine: {e}")
            return False
    
    async def create_goal(self, description: str, priority: Priority = Priority.MEDIUM,
                         deadline: Optional[datetime] = None,
                         intrinsic_values: Optional[Dict[str, float]] = None,
                         state_conditions: Optional[List[str]] = None) -> Optional[Goal]:
        """Create a new goal, optionally as a STATE goal.

        `state_conditions` is what makes a goal planned rather than merely
        described. Goal.goal_type derives from it -- STATE when present,
        DESCRIPTIVE otherwise -- and only a STATE goal reaches
        _plan_state_goal, which is the single path that consults learned rules.

        There was no way to supply them. The field existed, the planner read it,
        and the only writer repo-wide was a test, so every goal any production
        generator produced was DESCRIPTIVE and the validated MOVE operator could
        never supply planning authority outside that test.
        """
        if not self.active:
            return None
        
        try:
            # Extract intrinsic motivation values if provided
            intrinsic = intrinsic_values or {}
            
            # Safely extract intrinsic values, ensuring they're floats
            def get_float_value(key: str, default: float = 0.5) -> float:
                value = intrinsic.get(key, default)
                if isinstance(value, dict):
                    # If it's a dict, try to extract a numeric value
                    value = value.get('value', default) if isinstance(value, dict) else default
                return float(value) if not isinstance(value, dict) else default
            
            goal = Goal(
                id=str(uuid4()),
                description=description,
                priority=priority,
                deadline=deadline,
                created_at=datetime.now(),
                status="active",
                expected_novelty=get_float_value("expected_novelty", 0.5),
                expected_competence_gain=get_float_value("expected_competence_gain", 0.5),
                curiosity_value=get_float_value("curiosity_value", 0.5),
                intrinsic_reward_potential=get_float_value("intrinsic_reward_potential", 0.5),
                state_conditions=list(state_conditions) if state_conditions else None
            )
            
            # Durable first. Registering in memory before the write meant a
            # failed store left a goal the caller was told did not exist, which
            # then vanished at restart while plans referenced it.
            await self._store_goal(goal)
            self.current_goals[goal.id] = goal

            self.stats["goals_created"] += 1
            logger.info(f"Created goal: {description} (intrinsic potential: {goal.intrinsic_reward_potential:.2f})")
            return goal
            
        except Exception as e:
            logger.error(f"Error creating goal: {e}")
            return None
    
    async def plan_for_goal(
        self, goal_id: str, context: Optional[Dict[str, Any]] = None
    ) -> "PlanningOutcome":
        """Plan for a goal, in the mode its TYPE requires, reporting honestly.

        Mode is selected by `goal.goal_type`, never by a planner having failed.
        A state goal that cannot be solved returns UNREACHABLE or INDETERMINATE
        and stops there; it does not fall through to template decomposition.
        That fallthrough is the original silent-success defect, and routing it
        through a delegation layer would only make it harder to see.
        """
        if not self.active:
            return PlanningOutcome(PlanningStatus.UNSUPPORTED_GOAL,
                                   reason="planning engine is not active")
        if goal_id not in self.current_goals:
            return PlanningOutcome(PlanningStatus.INVALID_GOAL,
                                   reason=f"unknown goal {goal_id}")

        goal = self.current_goals[goal_id]
        if goal.goal_type is GoalType.STATE:
            return await self._plan_state_goal(goal, context or {})

        plan = await self.generate_plan(goal_id, context)
        return PlanningOutcome(
            PlanningStatus.PLAN_FOUND if plan else PlanningStatus.UNSUPPORTED_GOAL,
            plan=plan, planning_mode="template",
            reason="" if plan else "template decomposition produced no plan",
        )

    async def _plan_state_goal(
        self, goal: Goal, context: Dict[str, Any]
    ) -> "PlanningOutcome":
        """Search over grounded learned operators for a goal stated over state.

        The world state comes from the caller; nothing here invents one. Without
        it there is no problem to solve, and guessing an empty world would make
        every goal unreachable for a reason that is about the caller rather than
        the world.
        """
        from core.learning.rule_grounding import ground_for_problem
        from core.learning.rule_induction import Fact
        from core.learning.rule_store import get_rule_store
        from core.reasoning.temporal_reasoning import TemporalReasoningSystem

        world = context.get("world_state")
        if world is None:
            return PlanningOutcome(
                PlanningStatus.INDETERMINATE, planning_mode="state",
                reason="no world_state supplied; the goal cannot be evaluated",
            )

        state_facts = [Fact.parse(str(c)) for c in world]

        # A GOAL MAY STATE THAT A FACT MUST NOT HOLD. The search understands
        # negation and works over formulas; GROUNDING needs the positive fact
        # underneath, because that is the fact an operator's effects touch.
        #
        # Parsing every condition as a positive Fact made a negative goal
        # unplannable THROUGH THIS AUTHORITY — `¬FILE_IN(...)` is not an
        # identifier — even though the substrate learned REMOVE_FILE precisely to
        # satisfy one, and the raw planner has handled negation since that gap
        # was closed. The capability existed; this path could not reach it.
        goal_formulas: List[str] = []
        goal_facts: List[Fact] = []
        for condition in (goal.state_conditions or []):
            text = str(condition).strip()
            core, negated = text, False
            for marker in ("¬", "NOT ", "not "):
                if core.startswith(marker):
                    core, negated = core[len(marker):].strip(), True
                    break
            fact = Fact.parse(core)
            goal_facts.append(fact)
            goal_formulas.append(f"¬{fact.to_formula()}" if negated
                                 else fact.to_formula())

        # A GOAL NAMES PLACES, AND THE SELF LOOKS AT THEM. The world the caller
        # read is what the self had met; where a move is to put something is a
        # place nothing is at yet, and no look at a workspace finds it. What the
        # domain's world sees of the things the goal names is added wherever the
        # caller's reading says nothing about them.
        from core.execution.operator_binding import get_binding_registry
        seen = get_binding_registry().look_at(
            context.get("domain_id"),
            [fact.args[0] for fact in goal_facts
             if fact.args and not fact.args[0].startswith("?")])
        if seen:
            mentioned = {term for fact in state_facts for term in fact.args}
            state_facts += [fact for fact in sorted(seen, key=str)
                            if fact.args and fact.args[0] not in mentioned]

        rules = await get_rule_store().executable_rules(
            domain_id=context.get("domain_id"))
        grounding = ground_for_problem(rules, state_facts, goal_facts)

        result = TemporalReasoningSystem().plan_for_state_goal(
            goal_formulas,
            {"conditions": [f.to_formula() for f in state_facts]},
            grounding.to_actions(),
        )

        # An exhausted search only proves impossibility if the search was given
        # every operator. With a truncated grounding, "no plan" is ignorance
        # about Lyric's own learned repertoire, not a fact about the world.
        status = result.status
        reason = result.reason
        if status is PlanningStatus.UNREACHABLE and not grounding.complete:
            status = PlanningStatus.INDETERMINATE
            reason = (
                f"{result.reason}; but grounding was truncated, so unreached is "
                f"not unreachable"
            )

        if status is not PlanningStatus.PLAN_FOUND:
            return PlanningOutcome(
                status, planning_mode="state", reason=reason,
                goal_conditions=list(result.goal_conditions),
                grounding_complete=grounding.complete,
                operators_considered=len(grounding.operators),
            )

        # THE PROVED ROUTE IS RECORDED AS THE GOAL'S INTENT, through the authority
        # that owns intent. If reasoning already opened an intent when this goal
        # was raised, this FIRMS IT UP with the route that was actually proved
        # rather than starting a second account of the same pursuit.
        recorded = await self._record_plan_intent(goal, result, grounding, context)

        plan_id = str(uuid4())
        tasks = state_plan_to_tasks(result, goal, plan_id, grounding.complete,
                                    domain_id=context.get("domain_id"),
                                    intent_id=recorded.get("intent_id"))
        plan = Plan(
            id=plan_id, goal_id=goal.id, tasks=tasks,
            estimated_duration=self._estimate_plan_duration(tasks),
            confidence=1.0,  # the plan is proved, not estimated
            created_at=datetime.now(), status="active",
            # A STATE plan declares different inputs from a template one: the
            # world the coordinator observed, the operators the substrate learned,
            # and what it has earned in this domain. Recorded so the plan carries
            # what it was formed on.
            metadata={"planning_mode": "state",
                      "confidence_source": "proved_by_search",
                      # THE WORLD THIS ROUTE WAS PROVED AGAINST. A plan is a
                      # route from a state, so when a pursuit stops the first
                      # question is whether the state it started from still
                      # holds — and that cannot be asked unless the plan says
                      # what it was. Recorded as the observed facts, which is
                      # what `_observe_world` returns, so the comparison is
                      # against the same reading and not a re-derivation of it
                      # -- including what was looked at for the goal itself.
                      "planned_world": sorted(str(f) for f in state_facts),
                      "inputs": await self.assemble_inputs("state", goal, context),
                      # Which intent this plan is the proved route of, or why it
                      # has none. The account lives in the authority; this is the
                      # reference to it.
                      "intent": recorded},
        )
        await self._store_plan(plan)
        self.active_plans[plan.id] = plan
        self.stats["plans_generated"] += 1

        logger.info(
            "state plan for %s: %d step(s) from %d grounded operator(s)",
            goal.id, len(tasks), len(grounding.operators),
        )
        return PlanningOutcome(
            PlanningStatus.PLAN_FOUND, plan=plan, planning_mode="state",
            reason=result.reason, goal_conditions=list(result.goal_conditions),
            grounding_complete=grounding.complete,
            operators_considered=len(grounding.operators),
        )

    async def generate_plan(self, goal_id: str, context: Optional[Dict[str, Any]] = None) -> Optional[Plan]:
        """Template decomposition for a descriptive goal.

        Legal only because the goal has no state semantics. A state goal must
        never arrive here -- see plan_for_goal, which routes by type.
        """
        if not self.active or goal_id not in self.current_goals:
            return None

        # THE GUARD IS NOT AN ERROR, so it is raised OUTSIDE the try below. It
        # used to sit inside, where the blanket `except Exception` swallowed it
        # and returned None — the refusal held, but a caller could not tell a
        # deliberate refusal from the planner breaking.
        goal = self.current_goals[goal_id]
        if goal.goal_type is GoalType.STATE:
            raise ValueError(
                f"goal {goal_id} states world conditions and must be planned "
                f"by search, not decomposed into a task template"
            )

        try:
            # Generate tasks for the goal
            tasks = await self._generate_tasks_for_goal(goal, context or {})

            # WHAT THIS PLAN CLAIMS ABOUT ITSELF IS MEASURED, NOT INVENTED.
            # A template decomposition proves nothing, so its confidence and
            # duration are read from what the substrate has actually recorded
            # about the tools these tasks would use. Where nothing has been
            # measured, the absence is reported rather than filled in.
            confidence, duration, provenance = await self._measured_plan_claims(tasks)
            # Exactly the inputs a TEMPLATE plan declares it needs — tool history,
            # abstraction, episodic memory — each from the authority that owns it,
            # with anything missing reported as missing rather than skipped.
            provenance["inputs"] = await self.assemble_inputs(
                "template", goal, context or {})

            plan = Plan(
                id=str(uuid4()),
                goal_id=goal_id,
                tasks=tasks,
                estimated_duration=duration,
                confidence=confidence,
                created_at=datetime.now(),
                status="active",
                metadata=provenance,
            )
            
            self.active_plans[plan.id] = plan
            # THE ACCOUNT FOR MAKING THE THING. Recorded before the plan is
            # stored, and registered in `active_plans` first so the constitution
            # can find the plan when it checks the claim.
            await self._account_for_creation_steps(plan, goal)
            await self._store_plan(plan)

            self.stats["plans_generated"] += 1
            logger.info(f"Generated plan for goal: {goal.description}")
            return plan
            
        except Exception as e:
            logger.error(f"Error generating plan: {e}")
            return None
    
    #: A plan is not dispatched forever. Below this, an unfinished plan is
    #: simply slow; past it, nothing is working on it.
    #:
    #: The horizon is DERIVED FROM THE PLAN, not picked: a plan records how long
    #: it estimated it would take, so being an order of magnitude past its own
    #: estimate is the plan's own measure of abandoned. The floor keeps a plan
    #: that estimated thirty seconds from being retired during one slow cycle.
    PLAN_STALE_FLOOR_SECONDS: float = 3600.0
    PLAN_STALE_ESTIMATE_MULTIPLE: float = 10.0

    def _plan_is_stale(self, plan: "Plan", now: datetime) -> bool:
        """Has this plan been active so long that nothing can be working on it?"""
        created = getattr(plan, "created_at", None)
        if created is None:
            return False
        tasks = plan.tasks or []
        if tasks and not any(t.status == TaskStatus.PENDING for t in tasks):
            # NOTHING LEFT TO DISPATCH. Every step has finished or failed, so
            # this plan is over whatever its status field still says, and
            # holding slots for steps that can never run again is the jam
            # itself. This catches a plan that failed outright, which age alone
            # would leave sitting for an hour first.
            return True
        if any(t.status == TaskStatus.COMPLETED for t in tasks):
            # It is making progress. Slow is not abandoned.
            return False
        horizon = max(self.PLAN_STALE_FLOOR_SECONDS,
                      self.PLAN_STALE_ESTIMATE_MULTIPLE *
                      float(getattr(plan, "estimated_duration", 0.0) or 0.0))
        return (now - created).total_seconds() > horizon

    async def retire_stale_plans(self) -> List[str]:
        """Stop dispatching plans nothing is working on, and say which.

        WHY THIS EXISTS. `get_next_tasks` sorts by priority then OLDEST FIRST and
        returns `available_tasks[:max_concurrent_tasks]`. A plan whose tasks
        never complete is never removed, so it holds its dispatch slots forever
        — and `_load_state` restores every plan with `status='active'` on every
        boot, with no age bound, so a restart brings them all back.

        Measured before this existed: 156 active plans, 148 of them over a day
        old and the oldest from a month earlier, EVERY ONE with zero completed
        tasks. Three plans had ever completed. A freshly planned five-step goal
        received zero dispatch slots; all five went to test residue. The queue
        reported healthy and the substrate did nothing.

        Retired, not deleted: the plan becomes 'abandoned' and its row stays, so
        what was attempted is still on record.
        """
        now = datetime.now()
        retired: List[str] = []
        for plan in list(self.active_plans.values()):
            if plan.status == "active" and self._plan_is_stale(plan, now):
                plan.status = "abandoned"
                self.active_plans.pop(plan.id, None)
                retired.append(plan.id)
                try:
                    await self._store_plan(plan)
                except Exception as e:
                    raise_if_structural(e, 'planning_engine.retire_stale_plans')
                    logger.error("could not record plan %s as abandoned: %s",
                                 plan.id, e)
        if retired:
            logger.info("retired %d stale plan(s); they were holding dispatch "
                        "slots nothing was working on", len(retired))
        return retired

    async def get_next_tasks(self, system_state: SystemState) -> List[Task]:
        """Get next tasks to execute based on current system state.

        Authority changes are drained FIRST, because this is the single point
        where work leaves the planner. Draining anywhere else would leave a
        window in which a task authorised by a refuted rule could still be
        handed out.

        If the drain cannot run, nothing is dispatched. Dispatching on unknown
        authority is the failure this ordering exists to prevent, and an empty
        cycle is recoverable where an unauthorised action is not.
        """
        available_tasks = []

        # BEFORE ANYTHING IS HANDED OUT. A stale plan holds slots by being old —
        # the sort is oldest-first within a priority — so retiring has to happen
        # on the dispatch path, not only at boot, or a long-running process
        # never recovers the slots.
        try:
            await self.retire_stale_plans()
        except Exception as e:
            raise_if_structural(e, 'planning_engine.get_next_tasks')
            logger.error("could not retire stale plans: %s", e)

        try:
            await self.consume_rule_authority_changes()
        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'planning_engine.get_next_tasks')
            logger.error(
                "cannot confirm rule authority is current (%s) — dispatching "
                "nothing this cycle", e)
            return []

        try:
            # Get all ready tasks from active plans
            for plan in self.active_plans.values():
                if plan.status != "active":
                    continue
                
                for task in plan.tasks:
                    if (task.status == TaskStatus.PENDING and 
                        self._can_execute_task(task, system_state)):
                        available_tasks.append(task)
            
            # Sort by priority and dependencies
            def get_priority_value(task):
                """Safely extract priority value for sorting"""
                try:
                    if isinstance(task.priority, Priority):
                        # It's a Priority enum - use the enum ordering
                        priority_order = {
                            Priority.LOW: 0,
                            Priority.MEDIUM: 1,
                            Priority.HIGH: 2,
                            Priority.CRITICAL: 3
                        }
                        return priority_order.get(task.priority, 1)
                    elif hasattr(task.priority, 'value'):
                        # It's an enum with a value attribute
                        priority_map = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
                        return priority_map.get(str(task.priority.value).lower(), 1)
                    elif isinstance(task.priority, str):
                        # Convert string to numeric value for sorting
                        priority_map = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
                        return priority_map.get(task.priority.lower(), 1)
                    elif isinstance(task.priority, (int, float)):
                        # Already numeric
                        return float(task.priority)
                    else:
                        # Unknown type, use default
                        logger.warning(f"Unknown priority type for task {task.id}: {type(task.priority)}")
                        return 1
                except Exception as e:
                    # `except` must not turn a wiring defect into an empty result.
                    raise_if_structural(e, 'planning_engine.get_next_tasks')
                    logger.error(f"Error extracting priority value: {e}")
                    return 1
            
            available_tasks.sort(key=lambda t: (-get_priority_value(t), t.created_at.timestamp()))
            
            # Limit to max concurrent tasks
            return available_tasks[:self.max_concurrent_tasks]
            
        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'planning_engine.get_next_tasks')
            logger.error(f"Error getting next tasks: {e}")
            return []
    
    async def update_task_status(self, task_id: str, status: TaskStatus, 
                                result: Optional[Dict[str, Any]] = None) -> bool:
        """Update task status and handle completion"""
        try:
            # Find and update task
            for plan in self.active_plans.values():
                for task in plan.tasks:
                    if task.id == task_id:
                        task.status = status
                        if result:
                            task.result = result
                        
                        if status == TaskStatus.COMPLETED:
                            task.completed_at = datetime.now()
                            self.stats["tasks_completed"] += 1
                            
                            # Check if plan is complete
                            await self._check_plan_completion(plan.id)
                        
                        await self._store_plan(plan)
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error updating task status: {e}")
            return False
    
    async def get_prioritized_goals(self, intrinsic_weight: float = 0.3) -> List[Goal]:
        """
        Get goals prioritized by both external priority and intrinsic motivation
        
        Args:
            intrinsic_weight: Weight given to intrinsic motivation (0.0-1.0)
                             0.0 = pure external priority, 1.0 = pure intrinsic motivation
        """
        prioritized = []
        
        for goal in self.current_goals.values():
            if goal.status != "active":
                continue
            
            # Convert priority to numeric value
            priority_values = {
                Priority.LOW: 0.25,
                Priority.MEDIUM: 0.5,
                Priority.HIGH: 0.75,
                Priority.CRITICAL: 1.0
            }
            external_priority = priority_values.get(goal.priority, 0.5)
            
            # Safely extract intrinsic reward potential (handle dict case)
            intrinsic_potential = goal.intrinsic_reward_potential
            if isinstance(intrinsic_potential, dict):
                intrinsic_potential = intrinsic_potential.get('value', 0.5)
            intrinsic_potential = float(intrinsic_potential) if not isinstance(intrinsic_potential, dict) else 0.5
            
            # Calculate combined priority score
            combined_score = (
                (1.0 - intrinsic_weight) * external_priority +
                intrinsic_weight * intrinsic_potential
            )
            
            prioritized.append((combined_score, goal))
        
        # Sort by combined score (highest first)
        prioritized.sort(reverse=True, key=lambda x: x[0])
        
        return [goal for score, goal in prioritized]
    
    async def get_planning_status(self) -> Dict[str, Any]:
        """Get current planning status"""
        return {
            "active_goals": len(self.current_goals),
            "active_plans": len(self.active_plans),
            "pending_tasks": sum(
                1 for plan in self.active_plans.values() 
                for task in plan.tasks 
                if task.status == TaskStatus.PENDING
            ),
            "statistics": self.stats.copy()
        }
    
    #: The kinds of work a descriptive goal can name, in the order the work
    #: depends on: what is found gets analysed, what is analysed gets written.
    #: Several may be named at once, and then all of them are planned.
    _WORK_PHASES = (
        ("research", ("research", "investigate", "find out", "look up", "study",
                      "learn about", "gather")),
        ("analysis", ("analyz", "analys", "examine", "assess", "evaluate",
                      "compare")),
        ("creation", ("create", "write", "produce", "generate", "draft",
                      "build", "compose", "summar", "report")),
    )

    async def _generate_tasks_for_goal(self, goal: Goal, context: Dict[str, Any]) -> List[Task]:
        """Decompose a descriptive goal into the work it NAMES — ALL of it.

        FIRST MATCH WINS WAS DROPPING HALF THE GOAL. This was
        `if "research" … elif "analyze" … elif "create" …`, so
        "Research photosynthesis and create a written summary at <path>" planned
        RESEARCH and ANALYSIS and never planned the write at all. Measured in
        RESEARCH-WRITE-01: no file, no act, no demonstration, nothing to verify
        — and because a template plan carries no goal state, the plan reported
        done anyway. The failure read as "the substrate could not do it" when it
        had never been asked to.

        A goal may name several kinds of work. Each named phase is planned, and
        each is CHAINED to the one before it, so the step that writes the
        summary runs after the research it is supposed to be writing up rather
        than beside it.
        """
        tasks = []

        described = goal.description.lower()
        makers = {"research": self._generate_research_tasks,
                  "analysis": self._generate_analysis_tasks,
                  "creation": self._generate_creation_tasks}
        named = [phase for phase, words in self._WORK_PHASES
                 if any(word in described for word in words)]

        subject = self.subject_named_by(goal.description)
        # WRITING UP WHAT IS KNOWN ABOUT SOMETHING NEEDS THAT KNOWLEDGE GATHERED
        # FIRST. The creation step writes up the findings of the steps before it
        # and invents nothing, so "Create a written summary of what you know
        # about centrifugal pumps at <path>" -- a creation with a subject and no
        # step that says anything about it -- wrote nothing and could not.
        # Gathering answers from what is held first and looks further only on a
        # gap, so it is the step that produces the content.
        if subject and "creation" in named and "research" not in named:
            named.insert(0, "research")
        if named:
            previous: List[Task] = []
            for phase in named:
                stage = makers[phase](goal)
                # THE STEPS OF A STAGE HAPPEN IN ORDER TOO. Only stages were
                # chained, so a stage's own steps were all ready at once and the
                # step that checks the file ran beside -- or before -- the step
                # that writes it, and failed on an empty path.
                for before, after in zip(stage, stage[1:]):
                    after.dependencies = list(after.dependencies or []) + [before.id]
                if subject:
                    # WHAT THE WORK IS ABOUT travels with every step of it, so
                    # no step has to recover it from its own instruction.
                    for step in stage:
                        step.provenance = dict(step.provenance or {})
                        step.provenance["subject"] = subject
                if previous and stage:
                    # THE ORDER IS THE POINT. Without it the writer can run
                    # before the research and write up nothing.
                    stage[0].dependencies = list(stage[0].dependencies or []) + [previous[-1].id]
                tasks.extend(stage)
                previous = stage or previous
        else:
            # Default task breakdown
            tasks.append(Task(
                id=str(uuid4()),
                type=TaskType.RESEARCH,
                description=f"Research requirements for: {goal.description}",
                priority=goal.priority,
                estimated_duration=30.0,
                created_at=datetime.now()
            ))

            tasks.append(Task(
                id=str(uuid4()),
                type=TaskType.ANALYSIS,
                description=f"Analyze approach for: {goal.description}",
                priority=goal.priority,
                estimated_duration=20.0,
                created_at=datetime.now(),
                dependencies=[tasks[0].id]
            ))

            tasks.append(Task(
                id=str(uuid4()),
                type=TaskType.EXECUTION,
                description=f"Execute: {goal.description}",
                priority=goal.priority,
                estimated_duration=60.0,
                created_at=datetime.now(),
                dependencies=[tasks[1].id]
            ))

        # Enhance all tasks with tool suggestions
        enhanced_tasks = [self._enhance_task_with_tools(task) for task in tasks]

        return enhanced_tasks
    
    def _generate_research_tasks(self, goal: Goal) -> List[Task]:
        """Generate research-specific tasks"""
        return [
            Task(
                id=str(uuid4()),
                type=TaskType.RESEARCH,
                description=f"Information gathering for: {goal.description}",
                priority=goal.priority,
                estimated_duration=45.0,
                created_at=datetime.now()
            ),
            Task(
                id=str(uuid4()),
                type=TaskType.ANALYSIS,
                description=f"Analyze research findings for: {goal.description}",
                priority=goal.priority,
                estimated_duration=30.0,
                created_at=datetime.now()
            )
        ]
    
    def _generate_analysis_tasks(self, goal: Goal) -> List[Task]:
        """Generate analysis-specific tasks"""
        return [
            Task(
                id=str(uuid4()),
                type=TaskType.ANALYSIS,
                description=f"Data analysis for: {goal.description}",
                priority=goal.priority,
                estimated_duration=40.0,
                created_at=datetime.now()
            ),
            Task(
                id=str(uuid4()),
                type=TaskType.SYNTHESIS,
                description=f"Synthesize analysis results for: {goal.description}",
                priority=goal.priority,
                estimated_duration=25.0,
                created_at=datetime.now()
            )
        ]
    
    @staticmethod
    def artefact_named_by(description: str) -> Optional[str]:
        """The thing this goal says to CREATE, if it names one.

        THE PLANNER IS THE GOAL-READER. "create a written summary at
        /tmp/x/findings.md" names its own product, and the step that makes it
        cannot make it without knowing what it is. Reading that here — once,
        where the goal is already being read — is what lets the executor act on
        a target instead of guessing one, and what lets VALIDATION check the
        right thing afterwards.

        Returns None when the goal names no artefact, and a creation step then
        says so honestly rather than inventing a destination.
        """
        # A path-shaped token: at least one separator and a final segment. Not a
        # guess about filesystems -- it is the only thing in the sentence that
        # could be a destination, and if there is none there is no destination.
        candidates = re.findall(r"(?:/|~/)[\w./~-]*[\w-]", str(description or ""))
        return candidates[-1] if candidates else None

    @staticmethod
    def subject_named_by(description: str) -> Optional[str]:
        """WHAT this goal is about, as distinct from what it says to do.

        A step's description is an INSTRUCTION — "Information gathering for:
        Research photosynthesis and create a written summary at <path>" — and
        asking the knowledge loop about the whole sentence asks about the
        sentence. Measured: the loop took `summary` for the topic and the
        substrate wrote a correct, verified file that said "summary is a
        written or spoken work". A file about nothing, passing every check
        except the one that reads it.

        So the subject is read once, here, where the goal is already being read:
        what follows the instruction verb, up to where the instruction turns to
        what to DO with it. Returns None when the goal names no subject, and the
        loop then falls back to its own reading of the description.
        """
        text = " ".join(str(description or "").split())
        after = re.sub(
            r"^(?:please\s+)?(?:research|investigate|study|look\s+up|find\s+out"
            r"(?:\s+about)?|learn\s+about|gather\s+information\s+(?:on|about))\s+",
            "", text, flags=re.IGNORECASE)
        if after == text:
            # A GOAL TO MAKE SOMETHING NAMES ITS SUBJECT AFTER WHAT IT MAKES:
            # "a written summary of what you know ABOUT centrifugal pumps", "a
            # report ON cavitation", "a summary OF photosynthesis". The first
            # `about` wins; failing that, what a summary/report/note is of or on.
            found = (re.search(r"\babout\s+(.+)", text, flags=re.IGNORECASE)
                     or re.search(r"\b(?:summary|report|overview|description|notes?|"
                                  r"write-?up)\s+(?:of|on)\s+(?!what\b)(.+)",
                                  text, flags=re.IGNORECASE))
            if not found:
                return None
            after = found.group(1)
        # The subject ends where the goal starts saying what to do with it, or
        # where it names the destination ("... at /tmp/x/summary.md").
        subject = re.split(
            r"\s+(?:and|then|,|;|so\s+that|in\s+order\s+to)\s+"
            r"|\s+(?:at|to|in|into)\s+(?=[/~])",
            after, maxsplit=1, flags=re.IGNORECASE)[0]
        subject = subject.strip(" .:;")
        return subject or None

    def _generate_creation_tasks(self, goal: Goal) -> List[Task]:
        """Generate creation-specific tasks"""
        artefact = self.artefact_named_by(goal.description)
        # WHAT IS TO BE MADE TRAVELS WITH THE STEPS THAT MAKE AND CHECK IT.
        # Without it the creation step has a sentence and no target, and the
        # validation step has nothing to verify -- which is how a plan came to
        # report done with no file anywhere.
        made = {"artefact": artefact} if artefact else {}
        # No "plan the creation" step: this plan IS that, and the step that
        # asked for it again had no path that could carry it out, so every
        # creation plan held a step that could only fail.
        return [
            Task(
                id=str(uuid4()),
                type=TaskType.EXECUTION,
                description=f"Create: {goal.description}",
                priority=goal.priority,
                estimated_duration=90.0,
                created_at=datetime.now(),
                provenance=dict(made),
            ),
            Task(
                id=str(uuid4()),
                type=TaskType.VALIDATION,
                description=f"Validate creation: {goal.description}",
                priority=goal.priority,
                estimated_duration=15.0,
                created_at=datetime.now(),
                provenance=dict(made),
            )
        ]
    
    async def _account_for_creation_steps(self, plan: "Plan", goal: Goal) -> int:
        """Record WHY each step that must make something is happening.

        The constitution reads an account at the gate and recognised three:
        a proved route, an experiment, or looking. A plain instruction is none
        of them, so a step planned to write a file the goal explicitly asked for
        was refused as "an act nothing can explain" — measured in
        RESEARCH-WRITE-01, where every step succeeded and no file was ever
        written.

        Only the intent's ID travels, exactly as a proved plan's does. What is
        recorded here is checkable by `_carrying_out_is_earned` against this
        plan and this goal, so this states a claim rather than granting itself
        permission. A failure to record leaves the step with no account, and it
        is then refused — which is the correct answer to work nothing can
        explain, not a reason to act anyway.
        """
        stamped = 0
        for task in plan.tasks or []:
            artefact = (task.provenance or {}).get("artefact")
            if not artefact or task.type is not TaskType.EXECUTION:
                continue
            try:
                from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
                from core.reasoning.intent_authority import get_intent_authority

                intent = await get_intent_authority().form(
                    "goal", SUBSTRATE_ACTOR, f"plan:{plan.id}:{task.id}",
                    shape={
                        # `proved` is deliberately ABSENT: no route was proved
                        # over a learned operator, and claiming one would be the
                        # fabricated-intent hole the constitution closed.
                        "purpose": "carry_out",
                        "plan_id": plan.id,
                        "goal_id": goal.id,
                        "artefact": artefact,
                        "steps": len(plan.tasks or []),
                    })
                task.provenance = dict(task.provenance or {})
                task.provenance["intent_id"] = getattr(intent, "intent_id", None)
                task.provenance["plan_id"] = plan.id
                stamped += 1
            except Exception as e:
                raise_if_structural(e, 'planning_engine._account_for_creation_steps')
                logger.error("could not record an account for %s: %s — it will "
                             "be refused for having none", task.id, e)
        return stamped

    def _estimate_plan_duration(self, tasks: List[Task]) -> float:
        """Estimate total duration for plan execution"""
        return sum(task.estimated_duration for task in tasks)
    
    #: A schema must be this strong before it constrains planning. Below it, the
    #: regularity is not established enough to shape what the substrate does.
    SCHEMA_STRENGTH_FLOOR: float = 0.7

    # ── the proved route, recorded as intent ─────────────────────────────────

    async def _record_plan_intent(self, goal: Goal, result: Any, grounding: Any,
                                  context: Dict[str, Any]) -> Dict[str, Any]:
        """Record the proved route as this goal's INTENT, through the authority
        that owns intent.

        ONE GOAL IS ONE INTENT. The steps of a proved plan are the route within
        it, not separate intentions, so each task references this intent and says
        which step of it it is. If reasoning already opened an intent when the
        goal was raised, `form` finds it and firms it up with the route that was
        actually proved — it does not start a second account of the same pursuit.

        The split is made here, at the point of record: the reasoning skeleton
        (operators, the rules that license them, the goal state) is substrate-wide
        SHAPE; the goal's own words and the concrete bindings are the actor's
        CONTENT.

        Returns what happened — including a reason when nothing was recorded — so
        the plan carries an honest account of whether it has an intent behind it
        rather than appearing to have one.
        """
        from core.reasoning.intent_authority import (
            get_intent_authority, continuity_goal, SUBSTRATE_ACTOR)

        actor = str(context.get("actor") or SUBSTRATE_ACTOR)
        steps = list(getattr(result, "steps", []) or [])
        actions = list(getattr(result, "actions", []) or [])
        operators = [str(step.get("action")) for step in steps if step.get("action")]
        rule_ids = [a.get("rule_id") for a in actions if a.get("rule_id")]
        goal_conditions = [str(c) for c in (getattr(result, "goal_conditions", []) or [])]
        try:
            intent = await get_intent_authority().form(
                "goal", actor, continuity_goal(goal.id),
                shape={
                    # `proved` is the claim the constitution's Law 4 rests on, and
                    # it is true here BECAUSE the search found this route over
                    # operators the rule store attests are executable.
                    "proved": True,
                    "operator": operators[0] if operators else "",
                    "operators": operators,
                    "goal_conditions": goal_conditions,
                    "rule_ids": rule_ids,
                    "domain": context.get("domain_id"),
                    "steps": len(operators),
                    "grounding_complete": bool(getattr(grounding, "complete", True)),
                    "plan_guarantee": getattr(
                        getattr(result, "guarantee", None), "value", None),
                },
                content={
                    "aim": goal.description,
                    "bindings": [a.get("bindings", {}) for a in actions],
                },
                # The pursuit this goal was raised inside, when there is one.
                parent_intent_id=context.get("parent_intent_id"))
            return {"recorded": True, "intent_id": intent.intent_id,
                    "actor": actor, "operators": len(operators)}
        except Exception as e:
            # Not swallowed into a silent success: the plan will say it has no
            # intent behind it, and why, rather than appearing to have one.
            logger.error("the proved plan for goal %s was not recorded as intent: %s",
                         goal.id, e)
            return {"recorded": False, "intent_id": None, "reason": str(e)}

    # ── the inputs a plan needs, gathered through their owners ───────────────

    async def assemble_inputs(self, kind: str, goal: Goal,
                              context: Dict[str, Any]) -> Dict[str, Any]:
        """Gather exactly the inputs this KIND of plan declares it needs.

        Each is obtained through the authority that OWNS it, and what could not
        be obtained is reported as missing with a reason rather than quietly
        skipped — a plan formed without an input it declared is a plan formed on
        less than it said it needed.
        """
        required = PLAN_KIND_INPUTS.get(kind, ())
        gathered: Dict[str, Any] = {}
        missing: List[Dict[str, Any]] = []
        for need in required:
            obtained = await self._obtain_input(need, goal, context)
            if obtained.get("available"):
                gathered[need.value] = obtained
            else:
                missing.append({"input": need.value,
                                "reason": obtained.get("reason")})
        return {"kind": kind,
                "required": [need.value for need in required],
                "gathered": gathered,
                "missing": missing}

    async def _obtain_input(self, need: PlanInput, goal: Goal,
                            context: Dict[str, Any]) -> Dict[str, Any]:
        """One declared input, from its owner. Absence is reported, never filled."""
        try:
            if need is PlanInput.OBSERVED_WORLD:
                # The COORDINATOR perceives the environment; the planner is given
                # what it saw. The planner does not go and look for itself.
                world = context.get("world_state")
                if world is None:
                    return {"available": False,
                            "reason": "no observed world supplied by the coordinator"}
                return {"available": True, "source": "coordinator (perception)",
                        "facts": len(world)}

            if need is PlanInput.LEARNED_OPERATORS:
                from core.learning.rule_store import get_rule_store
                domain_id = context.get("domain_id")
                rules = await get_rule_store().executable_rules(domain_id=domain_id)
                if not rules:
                    return {"available": False,
                            "reason": f"the rule store holds no executable "
                                      f"operator for domain {domain_id!r}"}
                return {"available": True, "source": "rule store",
                        "operators": len(rules)}

            if need is PlanInput.TOOL_HISTORY:
                metrics = await self._measured_tool_metrics()
                if not metrics.get("available"):
                    return {"available": False, "reason": metrics.get("reason")
                            or "no tool history recorded"}
                return {"available": True, "source": "learning authority",
                        "runs": metrics.get("runs"),
                        "success_rate": metrics.get("success_rate")}

            if need in (PlanInput.ABSTRACTION, PlanInput.EPISODIC_MEMORY):
                hierarchical = await self._hierarchical_context(
                    goal, domain=context.get("domain_id") or "general")
                if not hierarchical.get("available"):
                    return {"available": False,
                            "reason": hierarchical.get("reason")}
                if need is PlanInput.ABSTRACTION:
                    return {"available": True, "source": "reasoning authority",
                            "principles": len(hierarchical.get("principles_applied") or []),
                            "schemas": len(hierarchical.get("schemas_considered") or []),
                            "constraints": hierarchical.get("strategy_constraints") or []}
                return {"available": True, "source": "memory, within abstraction",
                        "memories": hierarchical.get("supporting_memories") or []}

            if need is PlanInput.OPERATING_RELIABILITY:
                domain_id = context.get("domain_id")
                if not domain_id:
                    return {"available": False,
                            "reason": "no domain to read earned reliability for"}
                from core.integration.universal_domain_master import (
                    get_universal_domain_master)
                reliability = await get_universal_domain_master(
                    ).operating_reliability(domain_id)
                return {"available": True, "source": "domain authority",
                        **reliability}

            return {"available": False, "reason": f"unknown input {need!r}"}
        except Exception as e:
            logger.debug("planning input %s unavailable: %s", need.value, e)
            return {"available": False, "reason": str(e)}

    @staticmethod
    def _constrained_query(description: str, constraints: List[Dict[str, Any]]) -> str:
        """The memory query, narrowed by what the strongest schemas prefer."""
        parts = [description]
        for constraint in constraints[:3]:
            for key, value in (constraint.get("prefer") or {}).items():
                parts.append(f"{key}:{value}")
        return " ".join(parts)

    async def _memories_within(self, description: str,
                              constraints: List[Dict[str, Any]],
                              pipeline: Any) -> List[str]:
        """EPISODIC memories queried WITHIN the strategy constraints — ids only.

        Scoped to `MemoryType.EPISODIC` — specific past experiences — because that
        is what this step claims to consult. The planner this came from said
        "episodic" in its docstring while querying every memory type, so the claim
        and the query disagreed.

        `search_memories` returns either a list or a (ok, list) pair depending on
        the interface a caller uses; both are handled, because assuming one was a
        second latent bug in that planner.
        """
        from core.memory.utils.interfaces import MemoryType
        found = await pipeline.memory.search_memories(
            query_text=self._constrained_query(description, constraints),
            memory_types=[MemoryType.EPISODIC], limit=20)
        if isinstance(found, tuple):
            found = found[1] if len(found) > 1 else []
        return [m for m in
                (getattr(item, "memory_id", "") for item in (found or [])) if m]

    async def _hierarchical_context(self, goal: Goal,
                                    domain: str = "general") -> Dict[str, Any]:
        """Abstraction UPSTREAM of planning: the principles and schemas that bear
        on this goal, and the past experience falling WITHIN those constraints.

        Absorbed from the orphaned `HierarchicalPlanner`, which had no callers.
        Its METHOD is what is kept — principles → schemas beneath them → strategy
        constraints → episodic memory queried within those constraints — because
        that is what makes planning hierarchical, and it is how a plan draws on
        past memories rather than on the goal's wording alone.

        ITS FINAL STEP IS DELIBERATELY NOT KEPT. That emitted prose steps
        ("Apply strategy: {when} → {prefer}", "Based on past: {action}") — output
        shaped like a plan that proves nothing. Steps come from proved operators;
        this supplies the CONTEXT a plan is formed in, recorded as real ids.
        """
        from core.reasoning.hierarchical_abstraction import AbstractionLevel
        from core.reasoning.neural_bridge import get_neural_bridge
        # THROUGH THE REASONING AUTHORITY, which owns abstraction — not the
        # module-level global behind it.
        pipeline = getattr(get_neural_bridge(), "abstraction", None)
        if pipeline is None:
            return {"available": False,
                    "reason": "the reasoning authority has not brought up "
                              "abstraction yet"}
        try:
            hierarchy = pipeline.concept_hierarchy
            principles = hierarchy.find_principles_for_domain(domain)
            schemas = []
            for principle in principles:
                for node in hierarchy.get_descendants(principle.concept_id,
                                                      max_depth=1):
                    if node.level is AbstractionLevel.SCHEMA and node.schema_id:
                        schema = pipeline.active_schemas.get(node.schema_id)
                        if schema is not None:
                            schemas.append(schema)
            constraints = [
                {"when": s.condition, "prefer": s.outcome,
                 "confidence": s.probability, "schema_id": s.schema_id,
                 "evidence_count": s.evidence_count}
                for s in schemas if s.probability > self.SCHEMA_STRENGTH_FLOOR
            ]
            return {
                "available": True,
                "domain": domain,
                "principles_applied": [p.concept_id for p in principles],
                "schemas_considered": [s.schema_id for s in schemas],
                "strategy_constraints": constraints,
                "supporting_memories": await self._memories_within(
                    goal.description, constraints, pipeline),
            }
        except Exception as e:
            logger.debug("hierarchical context unavailable: %s", e)
            return {"available": False, "reason": str(e)}

    #: Neutral confidence, used ONLY when nothing relevant has been measured.
    #: Withheld both ways until earned — the same discipline as
    #: `operating_reliability`, which reports 0.5 rather than guessing until it
    #: has enough outcomes. It is paired with provenance saying it is unmeasured,
    #: so a caller can tell "no evidence yet" from "evidence says 0.5".
    UNMEASURED_CONFIDENCE: float = 0.5

    @staticmethod
    def _task_tool_names(task: Task) -> List[str]:
        """The tools this task says it would use."""
        return [str(t) for t in ((task.metadata or {}).get("suggested_tools") or [])]

    async def _measured_tool_metrics(self) -> Dict[str, Any]:
        """What the substrate has actually MEASURED about its tools — per-tool
        success rate and average latency.

        Read THROUGH THE LEARNING AUTHORITY, which owns what the substrate has
        learned and surfaces tool performance as part of it. The planner does not
        reach into the tool-metrics collector behind its owner's back. Never
        invents: when nothing is recorded it says so, and the caller reports the
        absence."""
        try:
            from core.learning import get_learning_authority
            metrics = await get_learning_authority().get_learning_metrics()
            usage = (metrics or {}).get("tool_usage")
            if not usage:
                return {"available": False,
                        "reason": "the learning authority has no tool usage recorded"}
            return usage
        except Exception as e:
            logger.debug("tool metrics unavailable to the planner: %s", e)
            return {"available": False, "reason": str(e)}

    async def _measured_plan_claims(
        self, tasks: List[Task]
    ) -> Tuple[float, float, Dict[str, Any]]:
        """(confidence, duration_minutes, provenance) for a template plan, read
        from measured tool history rather than constants.

        Confidence is the mean measured success rate of the tools these tasks
        would use; duration is their summed mean latency. Both report how they
        were derived, and when there is no history the provenance says
        `unmeasured` instead of a number pretending to be evidence.
        """
        metrics = await self._measured_tool_metrics()
        provenance: Dict[str, Any] = {"planning_mode": "template"}
        if not metrics.get("available"):
            provenance.update({
                "confidence_source": "unmeasured",
                "duration_source": "unmeasured",
                "reason": metrics.get("reason") or metrics.get("error")
                or "no tool metrics available",
            })
            return self.UNMEASURED_CONFIDENCE, 0.0, provenance

        by_tool = {row["tool"]: row for row in (metrics.get("by_tool") or [])}
        rates: List[float] = []
        total_ms = 0.0
        measured_tools: List[str] = []
        for task in tasks:
            for name in self._task_tool_names(task):
                row = by_tool.get(name)
                if not row:
                    continue
                if row.get("success_rate") is not None:
                    rates.append(float(row["success_rate"]))
                if row.get("avg_latency_ms") is not None:
                    total_ms += float(row["avg_latency_ms"])
                measured_tools.append(name)

        if rates:
            confidence = round(sum(rates) / len(rates), 4)
            provenance["confidence_source"] = "measured_tool_success_rate"
            provenance["tools_measured"] = sorted(set(measured_tools))
        elif metrics.get("success_rate") is not None:
            # No per-tool history for these tools; the substrate's overall
            # measured success rate is still a real reading.
            confidence = float(metrics["success_rate"])
            provenance["confidence_source"] = "measured_overall_success_rate"
            provenance["runs"] = metrics.get("runs")
        else:
            confidence = self.UNMEASURED_CONFIDENCE
            provenance["confidence_source"] = "unmeasured"

        if total_ms > 0:
            duration = round(total_ms / 60000.0, 4)      # ms -> minutes
            provenance["duration_source"] = "measured_tool_latency"
        else:
            duration = 0.0
            provenance["duration_source"] = "unmeasured"
        return confidence, duration, provenance
    
    def _can_execute_task(self, task: Task, system_state: SystemState) -> bool:
        """Check if task can be executed given current system state.

        Dependencies fail CLOSED. The previous form was
        `if dep_id in dep_tasks and ... != COMPLETED`, so a dependency id that
        matched no known task read as "no blocker" rather than "cannot be
        satisfied". Ordering in a state plan is carried entirely by these
        chains, so an unresolvable id there would let steps run out of
        sequence -- with each step's preconditions established by the one
        before it, that is silent corruption rather than a visible failure.
        """
        if task.dependencies:
            known: Dict[str, Task] = {}
            for plan in self.active_plans.values():
                known.update({t.id: t for t in plan.tasks})

            for dep_id in task.dependencies:
                dependency = known.get(dep_id)
                if dependency is None:
                    logger.error(
                        "task %s depends on unknown task %s — refusing to run it",
                        task.id, dep_id,
                    )
                    return False
                if dependency.status != TaskStatus.COMPLETED:
                    return False


        # Check resource requirements
        if system_state.resource_usage > 0.9:
            return task.priority == Priority.HIGH
        
        return True
    
    async def consume_rule_authority_changes(self) -> Dict[str, Any]:
        """Withdraw plans that stand on a rule which has lost its authority.

        Plans are authorised at planning time by the rules they ground. When a
        rule is refuted, every unrun step that depends on it is unauthorised —
        including steps queued behind a predecessor that completed perfectly.
        A dependency chain guarantees ORDER, not continued validity, so
        "my predecessor finished" is not a reason for the next step to run.

        The executor does not call this and does not know it exists. It writes
        down that authority changed; what that means for plans is decided here,
        which is where plans live.

        Completed work is left alone. It happened, and the rule was validated
        when it did — that is history, not something to retract.
        """
        from core.learning.rule_authority import (
            mark_consumed, pending_authority_changes)

        if not self.connection:
            raise RuntimeError("planning engine has no database connection")

        events = await pending_authority_changes(self.connection, lost_only=True)
        report = {
            "events": len(events),
            "plans_invalidated": [],
            "tasks_blocked": 0,
            "rules": sorted({e.rule_id for e in events}),
        }
        if not events:
            return report

        revoked = {e.rule_id for e in events}
        unrunnable = {TaskStatus.PENDING, TaskStatus.PLANNED,
                      TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}

        for plan in list(self.active_plans.values()):
            if plan.status != "active":
                continue

            affected = [
                task for task in plan.tasks
                if task.status in unrunnable
                and (task.provenance or {}).get("learned_rule_id") in revoked
            ]
            if not affected:
                continue

            for task in affected:
                task.status = TaskStatus.BLOCKED
                task.result = {
                    **(task.result or {}),
                    "blocked_reason": "learned_rule_lost_execution_authority",
                    "learned_rule_id": (task.provenance or {})["learned_rule_id"],
                }
            plan.status = "invalidated"
            plan.metadata = {
                **(plan.metadata or {}),
                "invalidated_by": "rule_authority_change",
                "revoked_rules": sorted(
                    {(t.provenance or {})["learned_rule_id"] for t in affected}),
                "invalidated_at": datetime.now().isoformat(),
            }
            await self._store_plan(plan)

            report["plans_invalidated"].append(plan.id)
            report["tasks_blocked"] += len(affected)
            logger.warning(
                "plan %s invalidated: %d step(s) depended on a rule that lost "
                "execution authority (%s)",
                plan.id, len(affected), ", ".join(plan.metadata["revoked_rules"]),
            )

        # Drained only after the plans are durably written. Marking first would
        # let a crash in between lose the event and leave an invalidated plan
        # still queued, with nothing left to say why it should not be.
        report["drained"] = await mark_consumed(
            [e.event_id for e in events], "planning_engine")

        # THE GOALS THOSE PLANS SERVED NOW HAVE NO ROUTE, and this is the only
        # moment anything knows which ones. Announced rather than repaired here:
        # replanning is a search and this runs inside `get_next_tasks`, the call
        # that asks what to run next. The reaction is deferred for that reason.
        stranded = self.withdrawn_goals()
        report["goals_stranded"] = stranded
        if stranded:
            await self._announce_route_withdrawal(stranded, report)
        return report

    async def _announce_route_withdrawal(self, stranded: List[str],
                                         report: Dict[str, Any]) -> None:
        """Say that these pursuits lost their route, through the substrate's own
        event dispatch.

        NOT BEST-EFFORT SILENCE. A withdrawal nothing hears leaves the goal
        exactly as stranded as having no repair at all, and the whole reason
        this exists is that such a state used to be invisible — so a failure to
        announce is logged as the unrepaired goals it actually is.
        """
        from core.agents.autonomous.runtime_registry import get_autonomous_coordinator

        coordinator = get_autonomous_coordinator()
        if coordinator is None:
            logger.error(
                "%d goal(s) lost their route and no live substrate is "
                "registered to hear it, so none will be replanned: %s",
                len(stranded), ", ".join(stranded))
            return
        try:
            await coordinator.announce_route_withdrawal(
                goal_ids=stranded, plan_ids=report["plans_invalidated"],
                rule_ids=report["rules"], tasks_blocked=report["tasks_blocked"])
        except Exception as e:
            logger.error(
                "the withdrawal of %d goal(s)' routes could not be announced "
                "(%s: %s); they stay stranded: %s",
                len(stranded), type(e).__name__, e, ", ".join(stranded))

    # ── the far end of the edge: the goal gets a new route ───────────────────

    def withdrawn_goals(self) -> List[str]:
        """Goals whose only route was withdrawn — an invalidated plan and no
        live one.

        STRANDED IS NOT THE SAME AS UNPLANNED. A goal that was never planned is
        waiting for whoever raised it; a goal whose proved route was taken away
        under it has nobody waiting, because the thing that would have planned
        it already did. Only the second is this engine's to repair, so the test
        is the presence of an invalidated plan, not merely the absence of an
        active one.
        """
        live, withdrawn = set(), set()
        for plan in self.active_plans.values():
            if plan.status == "active":
                live.add(plan.goal_id)
            elif plan.status == "invalidated":
                withdrawn.add(plan.goal_id)
        return sorted(
            goal_id for goal_id in withdrawn - live
            if (goal := self.current_goals.get(goal_id)) is not None
            and goal.status not in ("completed", "abandoned"))

    async def replan_withdrawn_goals(self) -> Dict[str, Any]:
        """Give a goal a new route when the one it stood on was taken away.

        THE NEAR END OF THIS EDGE WAS THE ONLY END THAT EXISTED. A runtime
        contradiction refutes a rule, the refutation is written durably, and
        `consume_rule_authority_changes` withdraws every plan standing on it --
        all correct, and all of it leaves the GOAL with nothing. Refuting a rule
        and stranding the pursuit it served is a worse failure than continuing
        to run the refuted rule would have been, because nothing reports it: the
        plan says `invalidated`, the goal says `active`, and no cycle ever asks
        again.

        Repair is driven by the ABSENCE OF A ROUTE, not run every cycle -- a
        goal that still has a live plan is not touched.

        THE WORLD IS RE-OBSERVED, NEVER REMEMBERED. A state goal is replanned
        against what the domain's bindings see NOW: the rule was refuted BY the
        world, so the world the withdrawn plan was proved against is precisely
        the account that turned out to be wrong. Where the world cannot be
        observed the goal is reported `unobservable` and left alone, because
        planning a state goal against an invented empty world would make every
        goal unreachable for a reason about this method rather than the world.

        `plan_for_goal` is the one entry, so the goal is replanned in the mode
        its TYPE requires and a state goal cannot fall through to template
        decomposition here any more than anywhere else.
        """
        from core.reasoning.temporal_reasoning import PlanningStatus

        stranded = self.withdrawn_goals()
        report: Dict[str, Any] = {
            "stranded": len(stranded), "replanned": 0, "unreachable": 0,
            "indeterminate": 0, "unobservable": 0, "goals": [], "routes": [],
        }
        for goal_id in stranded:
            goal = self.current_goals[goal_id]
            context = self._replan_context(goal_id)
            if context is None:
                report["unobservable"] += 1
                report["goals"].append({"goal_id": goal_id,
                                        "status": "unobservable"})
                logger.warning(
                    "goal %s lost its route and cannot be replanned: its domain "
                    "has no binding that can observe the world", goal_id)
                continue

            outcome = await self.plan_for_goal(goal_id, context)
            if outcome.status is PlanningStatus.PLAN_FOUND:
                report["replanned"] += 1
                # THE NEW ROUTE IS CARRIED OUT, not just named. A plan nothing
                # runs is not a repair, and the substrate that made it is the
                # only thing that can close it -- so the caller is handed what
                # it needs to pursue the route rather than a count of routes it
                # cannot reach.
                report["routes"].append({
                    "goal_id": goal_id, "plan": outcome.plan,
                    "domain_id": context.get("domain_id"),
                    "goal_conditions": list(outcome.goal_conditions
                                            or goal.state_conditions or []),
                })
                logger.info("goal %s was replanned after its route was withdrawn",
                            goal_id)
            elif outcome.status is PlanningStatus.UNREACHABLE:
                # A PROOF, so the pursuit ends rather than being retried on every
                # future withdrawal. INDETERMINATE is not: the search hit its
                # bound, and closing the goal on that would record ignorance as
                # impossibility.
                report["unreachable"] += 1
                goal.status = "abandoned"
                await self._store_goal(goal)
                logger.warning("goal %s is unreachable over what is still "
                               "validated: %s", goal_id, outcome.reason)
            else:
                report["indeterminate"] += 1
                logger.warning("goal %s could not be replanned (%s): %s",
                               goal_id, outcome.status.value, outcome.reason)
            report["goals"].append({"goal_id": goal_id,
                                    "status": outcome.status.value,
                                    "reason": outcome.reason})
        return report

    def _replan_context(self, goal_id: str) -> Optional[Dict[str, Any]]:
        """What planning this goal again needs, or None if it cannot be had.

        A descriptive goal needs nothing. A STATE goal needs the domain its
        withdrawn plan was proved in and a fresh reading of that domain's world;
        both are refused rather than guessed.
        """
        goal = self.current_goals[goal_id]
        if goal.goal_type is not GoalType.STATE:
            return {}

        domain_id = next(
            (step.provenance["domain_id"]
             for plan in self.active_plans.values()
             if plan.goal_id == goal_id and plan.status == "invalidated"
             for step in plan.tasks
             if (step.provenance or {}).get("domain_id")), None)
        if not domain_id:
            return None

        from core.execution.operator_binding import get_binding_registry

        # THE UNION OF WHAT EVERY BINDING IN THE DOMAIN SEES, which is what the
        # domain's world IS -- one predicate's observer sees one slice of it.
        observed = set()
        saw_anything = False
        for binding in get_binding_registry().bindings_for(domain_id):
            facts = binding.observe()
            if facts is None:
                continue          # this observer could not read; others may
            saw_anything = True
            observed |= set(facts)
        if not saw_anything:
            return None
        return {"world_state": sorted(observed, key=str), "domain_id": domain_id}

    async def _check_plan_completion(self, plan_id: str):
        """Check if plan is complete and update goal status"""
        if plan_id not in self.active_plans:
            return
        
        plan = self.active_plans[plan_id]
        completed_tasks = sum(1 for task in plan.tasks if task.status == TaskStatus.COMPLETED)
        
        if completed_tasks == len(plan.tasks):
            plan.status = "completed"
            plan.completed_at = datetime.now()
            
            # Update goal status
            if plan.goal_id in self.current_goals:
                self.current_goals[plan.goal_id].status = "completed"
                self.current_goals[plan.goal_id].completed_at = datetime.now()
            
            # Update success rate
            total_plans = self.stats["plans_generated"]
            completed_plans = sum(1 for p in self.active_plans.values() if p.status == "completed")
            self.stats["success_rate"] = completed_plans / total_plans if total_plans > 0 else 0.0
    
    async def _create_tables(self):
        """Ensure the goals and plans tables exist, with the real column types.

        These declarations previously disagreed with the tables a migration had
        already created -- priority VARCHAR against an INTEGER column, epoch
        DOUBLE PRECISION against TIMESTAMP, TEXT tasks against JSONB. Because
        the tables existed, CREATE TABLE IF NOT EXISTS was a permanent no-op and
        the disagreement was invisible until every INSERT failed on type.

        The deployed schema is authoritative; these match it. Raises on failure
        so initialize() cannot report success over a broken store.
        """
        if not self.connection:
            raise RuntimeError("planning engine has no database connection")

        await self.connection.execute_query("""
            CREATE TABLE IF NOT EXISTS goals (
                id VARCHAR(255) PRIMARY KEY,
                description TEXT NOT NULL,
                priority INTEGER,
                deadline TIMESTAMP,
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                status VARCHAR(50) DEFAULT 'active'
            )
        """, commit=True)

        await self.connection.execute_query("""
            CREATE TABLE IF NOT EXISTS plans (
                id VARCHAR(255) PRIMARY KEY,
                goal_id VARCHAR(255),
                tasks JSONB NOT NULL,
                estimated_duration INTEGER,
                confidence NUMERIC,
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                status VARCHAR(50) DEFAULT 'active'
            )
        """, commit=True)

        logger.debug("Goals and plans tables ready")

    async def _store_goal(self, goal: Goal):
        """Store goal in database.

        Raises on failure. This previously wrote `goal.priority.name` into an
        INTEGER column and `.timestamp()` floats into TIMESTAMP columns, caught
        the resulting error and logged it, so create_goal reported success and
        incremented its counter while no goal was ever written -- in production
        or anywhere. The types below are the ones unified.goals actually has.
        """
        if not self.connection:
            raise RuntimeError("planning engine has no database connection")

        await self.connection.execute_query(
            """
            INSERT INTO goals
            (id, description, priority, deadline, created_at, completed_at, status,
             state_conditions)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                description = EXCLUDED.description,
                priority = EXCLUDED.priority,
                deadline = EXCLUDED.deadline,
                completed_at = EXCLUDED.completed_at,
                status = EXCLUDED.status,
                state_conditions = EXCLUDED.state_conditions
            """,
            params=(
                goal.id, goal.description, PRIORITY_ORDINAL[goal.priority],
                goal.deadline, goal.created_at, goal.completed_at, goal.status,
                # Persisted, or a goal comes back from restart having silently
                # become DESCRIPTIVE -- losing its planning authority exactly
                # when the plan it belongs to needs resuming.
                json.dumps(list(goal.state_conditions)) if goal.state_conditions else None,
            ),
            commit=True,
        )

    async def _store_plan(self, plan: Plan):
        """Store plan in database. Raises on failure; see _store_goal."""
        if not self.connection:
            raise RuntimeError("planning engine has no database connection")

        tasks_json = json.dumps([
            {
                "id": task.id,
                "type": task.type.name,
                "description": task.description,
                "priority": task.priority.name,
                "status": task.status.name,
                "estimated_duration": task.estimated_duration,
                "created_at": task.created_at.isoformat(),
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "dependencies": task.dependencies,
                "result": task.result,
                "provenance": task.provenance,
            }
            for task in plan.tasks
        ])

        await self.connection.execute_query(
            """
            INSERT INTO plans
            (id, goal_id, tasks, estimated_duration, confidence, created_at, completed_at, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                tasks = EXCLUDED.tasks,
                estimated_duration = EXCLUDED.estimated_duration,
                confidence = EXCLUDED.confidence,
                completed_at = EXCLUDED.completed_at,
                status = EXCLUDED.status
            """,
            params=(
                plan.id, plan.goal_id, tasks_json,
                # estimated_duration is INTEGER and confidence NUMERIC in the
                # table this actually writes to.
                int(round(plan.estimated_duration or 0)),
                Decimal(str(round(float(plan.confidence or 0.0), 6))),
                plan.created_at, plan.completed_at, plan.status,
            ),
            commit=True,
        )

    async def _load_persistent_state(self):
        """Load goals and plans from database"""
        if not self.connection:
            return

        try:
            # Load goals
            goal_rows = await self.connection.execute_query(
                "SELECT * FROM goals WHERE status = 'active'",
                fetch_all=True
            )

            if goal_rows:
                for row in goal_rows:
                    goal = Goal(
                        id=row['id'],
                        description=row['description'],
                        # The columns are INTEGER and TIMESTAMP; the previous
                        # reader assumed a name string and epoch floats, so it
                        # could not have loaded a row even if one existed.
                        priority=priority_from_ordinal(row['priority']),
                        deadline=row['deadline'],
                        created_at=row['created_at'],
                        completed_at=row['completed_at'],
                        status=row['status'],
                        expected_novelty=0.5,
                        expected_competence_gain=0.5,
                        curiosity_value=0.5,
                        intrinsic_reward_potential=0.5,
                        state_conditions=(
                            json.loads(row['state_conditions'])
                            if isinstance(row.get('state_conditions'), str)
                            else row.get('state_conditions'))
                    )
                    self.current_goals[goal.id] = goal

            # Load plans
            plan_rows = await self.connection.execute_query(
                "SELECT * FROM plans WHERE status = 'active'",
                fetch_all=True
            )

            if plan_rows:
                for row in plan_rows:
                    tasks_data = json.loads(row['tasks'])
                    tasks = []
                    for task_data in tasks_data:
                        task = Task(
                            id=task_data["id"],
                            type=TaskType[task_data["type"]],
                            description=task_data["description"],
                            priority=Priority[task_data["priority"]],
                            status=TaskStatus[task_data["status"]],
                            estimated_duration=task_data["estimated_duration"],
                            created_at=datetime.fromisoformat(task_data["created_at"]),
                            completed_at=(datetime.fromisoformat(task_data["completed_at"])
                                          if task_data["completed_at"] else None),
                            dependencies=task_data["dependencies"],
                            result=task_data["result"],
                            provenance=task_data.get("provenance"),
                        )
                        tasks.append(task)

                    plan = Plan(
                        id=row['id'],
                        goal_id=row['goal_id'],
                        tasks=tasks,
                        estimated_duration=row['estimated_duration'],
                        confidence=float(row['confidence']) if row['confidence'] is not None else 0.0,
                        created_at=row['created_at'],
                        completed_at=row['completed_at'],
                        status=row['status']
                    )
                    self.active_plans[plan.id] = plan

            # A RESTART MUST NOT RESURRECT THEM. The query above asks for every
            # plan still marked active, with no age bound, so without this a
            # boot restores a month of unfinished test runs and they hold the
            # dispatch slots again. Retiring here rather than adding a date to
            # the SQL keeps ONE rule for what stale means — `_plan_is_stale` —
            # instead of a second copy of it that can drift.
            retired = await self.retire_stale_plans()
            if retired:
                logger.info("boot: %d restored plan(s) were already stale and "
                            "were not returned to the queue", len(retired))

        except Exception as e:
            logger.error(f"Error loading persistent state: {e}")
    
    def _suggest_tools_for_task(self, task_type: TaskType) -> List[str]:
        """Suggest appropriate tools for a task type"""
        tool_suggestions = {
            TaskType.RESEARCH: [
                "semantic_search",
                "grep_search",
                "read_file",
                "list_directory"
            ],
            TaskType.ANALYSIS: [
                "analyze_code",
                "grep_search",
                "read_file",
                "semantic_search"
            ],
            TaskType.EXECUTION: [
                "run_python",
                "run_shell_command",
                "execute_sandbox",
                "write_file"
            ],
            TaskType.VALIDATION: [
                "read_file",
                "run_python",
                "analyze_code"
            ],
            TaskType.SYNTHESIS: [
                "read_file",
                "write_file",
                "semantic_search"
            ]
        }

        suggested = tool_suggestions.get(task_type, [])
        available_tools = self.tool_registry.list_tools()

        # Return only tools that are actually registered
        return [tool for tool in suggested if tool in available_tools]

    def _enhance_task_with_tools(self, task: Task) -> Task:
        """Enhance task with appropriate tool metadata"""
        suggested_tools = self._suggest_tools_for_task(task.type)

        if suggested_tools:
            if not task.metadata:
                task.metadata = {}
            task.metadata["suggested_tools"] = suggested_tools
            task.metadata["tool_enabled"] = True
            self.stats["tools_planned"] += 1

            logger.debug(f"Task '{task.description}' enhanced with {len(suggested_tools)} tool suggestions")

        return task

    async def shutdown(self):
        """Shutdown the planning engine"""
        self.active = False
        if self.connection:
            self.connection.close()
            self.connection = None
        logger.info("Planning engine shutdown completed")