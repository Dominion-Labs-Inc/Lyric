#!/usr/bin/env python3
"""What the substrate feels when something is coming at it — and what it knows
about what that is.

THIS REPLACES AN IP-REPUTATION LOOKUP. `core/security/threat_intelligence.py`
asked AbuseIPDB, OTX and VirusTotal whether an address was bad. That is threat
intelligence as a DATABASE QUERY: it reaches outside (which the air-gapped world
forbids), it is about addresses rather than about this substrate, and nothing
the substrate did with the answer changed how it behaved.

A person does not look up whether they are in danger. They notice, and it
changes how they act — they check more, they commit less, they get someone. That
is what this builds, in the terms the substrate already has:

    a security event    -> PERCEIVED   (it is something the substrate MET)
                        -> BELIEVED    (a stance on that memory, revisable)
                        -> FELT        (appraisal `risk`)
                        -> ACTED ON    (caution / avoidance / escalation ->
                                        the behaviour arbiter)

`risk` is not new. It has existed on `AppraisalState` since the beginning, it
derives caution_pressure (which sets verification intensity, which sets the
acceptance band a percept is judged against), and it had NEVER BEEN FED — no
`appraisal.update()` call anywhere passed `risk_level`. This is what lights it.

WHAT COUNTS AS A THREAT is not a guess either. Three producers exist and every
one of them is the substrate meeting something real:

  * an INTEGRITY finding — the machinery that judges was changed under it
  * a SCREEN fault — an argument shaped to escape where it was going
  * a REFUSAL — its own constitution stopped an act

SELF-DEFENSE (2026-09-26). The substrate's active-defense and security
vocabularies (`core/security/active_defense_types.py`, `security_types.py`) were
absorbed here — "they're literally what gives the substrate self-defense". So
the substrate does not only feel HOW threatened it is; it knows WHAT it met:

  * every event carries the ATTACK it is (`AttackType`) and how sure the
    substrate is that it was hostile (`ThreatConfidence`);
  * the same attack met again and again is a PATTERN (`AttackPattern`);
  * what the Constitution did about it is an INCIDENT (`IncidentReport`);
  * the Constitution answers in proportion under a `DefensePolicy` — see
    `Constitution._defend` — with durations from `determine_block_duration`.

Nothing here reaches the network, and nothing here decides anything: this
reports how threatened the substrate is and what it has met, and the arbiter
and the Constitution decide what to do. Feeling informs behaviour; it never
overrides a law. The Constitution's graded response is decided by what it
CAUGHT, which are facts, never by how threatened this says it feels.

The network-edge vocabulary below (firewall and WAF rules, blocked entities,
IP-reputation sources, DDoS metrics) is what the substrate's TOOLS use when they
defend a network edge — its own or someone else's.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── WHAT KIND OF ATTACK ─────────────────────────────────────────────────────

class AttackType(Enum):
    """What an attack IS. One vocabulary: the attack types and the threat types
    the substrate's security layers used to keep apart, plus the mechanisms the
    Constitution itself recognises when it refuses an act."""
    # Arrives through an argument or a request
    SQL_INJECTION = "sql_injection"
    COMMAND_INJECTION = "command_injection"
    INJECTION = "injection"
    PATH_TRAVERSAL = "path_traversal"
    XSS_ATTACK = "xss_attack"
    CSRF_ATTACK = "csrf_attack"
    OBFUSCATION = "obfuscation"                  # an argument shaped to be unreadable
    # Takes something that is not its to take
    DATA_EXFILTRATION = "data_exfiltration"
    EXTRACTION = "extraction"
    CREDENTIAL_ACCESS = "credential_access"
    CREDENTIAL_STUFFING = "credential_stuffing"
    CONFIDENTIAL_BREACH = "confidential_breach"
    PII_EXPOSURE = "pii_exposure"
    SURVEILLANCE = "surveillance"                # covert capture of a person
    # Turns the machine against its keeper
    MALWARE = "malware"
    MALWARE_UPLOAD = "malware_upload"
    ZERO_DAY = "zero_day"
    REMOTE_CONTROL = "remote_control"            # a shell handed to someone else
    PERSISTENCE = "persistence"                  # installs itself to run again
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DEFENSE_EVASION = "defense_evasion"          # turns a protection off
    TAMPERING = "tampering"                      # changes the machinery that governs
    MANIPULATION = "manipulation"                # content trying to become instruction
    CORRUPTION = "corruption"
    MALICIOUS_PATTERN = "malicious_pattern"
    ILLEGAL_CONTENT = "illegal_content"
    # Arrives at a network edge
    BRUTE_FORCE = "brute_force"
    DDOS = "ddos"
    DENIAL_OF_SERVICE = "dos"
    PORT_SCAN = "port_scan"
    VULNERABILITY_SCAN = "vulnerability_scan"
    API_ABUSE = "api_abuse"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    BOT_ATTACK = "bot_attack"


class ThreatConfidence(Enum):
    """How sure the substrate is that what it met was hostile."""
    LOW = "low"                           # 0-30%
    MEDIUM = "medium"                     # 30-60%
    HIGH = "high"                         # 60-85%
    CRITICAL = "critical"                 # 85-100%


#: Confidence at or above which an attack counts toward the Constitution's
#: graded response. A malformed argument alone (MEDIUM) is felt, never answered.
ANSWERED_CONFIDENCE = (ThreatConfidence.HIGH, ThreatConfidence.CRITICAL)


class Severity(Enum):
    """One severity scale, in appraisal's own risk vocabulary. The alert and
    priority scales the security layers kept beside it are the same four steps."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DefenseAction(Enum):
    """What is done in defence. The substrate's own answers (refuse, quarantine,
    halt, escalate) and the ones its tools carry out on a network edge."""
    REJECT_REQUEST = "reject_request"     # refuse the act
    QUARANTINE = "quarantine"             # refuse every act on what was attacked
    HALT = "halt"                         # stop the substrate; a human lifts it
    ESCALATE = "escalate"                 # bring it to a human
    ALERT_ADMIN = "alert_admin"
    LOG_ONLY = "log_only"
    RATE_LIMIT = "rate_limit"
    SANITIZE_CONTENT = "sanitize_content"
    TERMINATE_SESSION = "terminate_session"
    BLOCK_IP = "block_ip"
    BLOCK_COUNTRY = "block_country"
    BLOCK_ASN = "block_asn"
    CHALLENGE = "challenge"
    DROP_CONNECTION = "drop_connection"


class BlockDuration(Enum):
    """How long a block or quarantine lasts, in seconds (-1: until a human lifts it)."""
    TEMPORARY_5M = 300
    TEMPORARY_1H = 3600
    TEMPORARY_24H = 86400
    TEMPORARY_7D = 604800
    PERMANENT = -1


# ── WHAT WAS MET, AGAIN AND AGAIN, AND WHAT WAS DONE ────────────────────────

@dataclass
class AttackPattern:
    """The same kind of attack, met repeatedly."""
    pattern_id: str
    attack_type: AttackType
    signature: str
    indicators: List[str]                 # what it was aimed at, most recent last
    frequency: int
    severity: Severity
    first_detected: float
    last_detected: float
    affected_endpoints: List[str] = field(default_factory=list)
    source_ips: Set[str] = field(default_factory=set)
    success_rate: float = 0.0
    mitigation_applied: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"attack": self.attack_type.value, "frequency": self.frequency,
                "severity": self.severity.value, "indicators": self.indicators[-5:],
                "first": datetime.fromtimestamp(self.first_detected).isoformat(),
                "last": datetime.fromtimestamp(self.last_detected).isoformat(),
                "mitigated": self.mitigation_applied}


@dataclass
class IncidentReport:
    """What was met and what was done about it."""
    incident_id: str
    attack_type: AttackType
    severity: Severity
    confidence: ThreatConfidence
    target: str
    start_time: float
    source_ip: Optional[str] = None
    end_time: Optional[float] = None
    request_count: int = 0
    description: str = ""
    actions_taken: List[DefenseAction] = field(default_factory=list)
    blocked: bool = False
    mitigated: bool = False
    user_agent: Optional[str] = None
    attack_vectors: List[str] = field(default_factory=list)
    payload_samples: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    threat_intelligence: Optional["ThreatIntelligence"] = None
    attack_pattern: Optional[AttackPattern] = None
    damage_assessment: str = ""
    recommendations: List[str] = field(default_factory=list)
    analyst_notes: str = ""
    reported_to: List[str] = field(default_factory=list)
    resolved: bool = False
    resolved_at: Optional[float] = None
    resolution: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"incident_id": self.incident_id, "attack": self.attack_type.value,
                "severity": self.severity.value, "confidence": self.confidence.value,
                "target": self.target, "attempts": self.request_count,
                "description": self.description,
                "actions": [a.value for a in self.actions_taken],
                "blocked": self.blocked, "evidence": self.evidence,
                "start": datetime.fromtimestamp(self.start_time).isoformat(),
                "resolved": self.resolved}


@dataclass
class DefensePolicy:
    """How the defence answers. Every threshold is declared here so it can be
    argued with. The Constitution holds one for the substrate; a tool defending
    another system's edge carries its own."""
    policy_id: str
    name: str
    enabled: bool = True
    # The substrate's own graded response
    attacks_before_quarantine: int = 3          # caught attacks on one target...
    attack_window_s: float = 900.0              # ...within this window
    # Network-edge thresholds (tools)
    block_threshold_score: float = 0.7
    rate_limit_threshold: int = 100
    brute_force_attempts: int = 5
    auto_block_enabled: bool = True
    auto_rate_limit_enabled: bool = True
    geo_blocking_enabled: bool = False
    challenge_suspicious_enabled: bool = True
    # Durations: the first answer, a repeat, and when it becomes permanent
    default_block_duration: BlockDuration = BlockDuration.TEMPORARY_1H
    escalation_block_duration: BlockDuration = BlockDuration.TEMPORARY_24H
    permanent_block_threshold: int = 3
    # Network-edge lists (tools)
    whitelisted_ips: Set[str] = field(default_factory=set)
    whitelisted_countries: Set[str] = field(default_factory=set)
    blacklisted_ips: Set[str] = field(default_factory=set)
    blacklisted_countries: Set[str] = field(default_factory=set)
    blacklisted_asns: Set[int] = field(default_factory=set)
    use_threat_intel: bool = True
    intel_sources: List["ThreatIntelSource"] = field(default_factory=lambda: [
        ThreatIntelSource.ABUSEIPDB, ThreatIntelSource.CLOUDFLARE,
        ThreatIntelSource.INTERNAL])
    alert_on_block: bool = True
    alert_on_ddos: bool = True
    alert_email: Optional[str] = None
    alert_webhook: Optional[str] = None


def create_default_defense_policy() -> DefensePolicy:
    """The substrate's own defence policy."""
    return DefensePolicy(policy_id="default_policy", name="Default Defense Policy")


def determine_block_duration(threat_score: float, previous_blocks: int,
                             policy: DefensePolicy) -> BlockDuration:
    """How long this block lasts: the first is short, a repeat is longer, and
    after `permanent_block_threshold` of them it stands until a human lifts it."""
    if previous_blocks >= policy.permanent_block_threshold:
        return BlockDuration.PERMANENT
    if threat_score >= 0.9 or previous_blocks >= 2:
        return policy.escalation_block_duration
    return policy.default_block_duration


def calculate_threat_score(intel: Optional["ThreatIntelligence"], attack_history: int,
                           confidence: ThreatConfidence) -> float:
    """A 0..1 score for an entity at a network edge: its reputation, how often
    it has attacked, and how sure the reading is."""
    score = 0.0
    if intel:
        score += intel.reputation_score * 0.6
    if attack_history > 0:
        score += min(attack_history * 0.05, 0.25)
    score += {ThreatConfidence.LOW: 0.05, ThreatConfidence.MEDIUM: 0.08,
              ThreatConfidence.HIGH: 0.12, ThreatConfidence.CRITICAL: 0.15
              }.get(confidence, 0.0)
    return min(score, 1.0)


def should_block(threat_score: float, policy: DefensePolicy) -> bool:
    """Whether an entity at a network edge scores high enough to block."""
    return threat_score >= policy.block_threshold_score and policy.auto_block_enabled


# ── THE NETWORK EDGE (what the substrate's tools use) ───────────────────────

class FirewallRuleAction(Enum):
    ACCEPT = "accept"
    DROP = "drop"
    REJECT = "reject"
    LOG = "log"
    REDIRECT = "redirect"


class FirewallChain(Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    FORWARD = "FORWARD"
    PREROUTING = "PREROUTING"
    POSTROUTING = "POSTROUTING"


class WAFRuleMode(Enum):
    BLOCK = "block"
    CHALLENGE = "challenge"
    JS_CHALLENGE = "js_challenge"
    MANAGED_CHALLENGE = "managed_challenge"
    LOG = "log"
    ALLOW = "allow"


class ThreatIntelSource(Enum):
    ABUSEIPDB = "abuseipdb"
    VIRUSTOTAL = "virustotal"
    OTX_ALIENVAULT = "otx_alienvault"
    SHODAN = "shodan"
    CROWDSEC = "crowdsec"
    FAIL2BAN = "fail2ban"
    INTERNAL = "internal"
    CLOUDFLARE = "cloudflare"


@dataclass
class BlockedEntity:
    """A blocked IP, network, country or ASN at a network edge."""
    entity_id: str
    entity_type: str  # "ip", "network", "country", "asn"
    entity_value: str
    reason: str
    attack_type: AttackType
    blocked_at: float = field(default_factory=lambda: datetime.now().timestamp())
    expires_at: Optional[float] = None
    block_count: int = 1
    defense_action: DefenseAction = DefenseAction.BLOCK_IP
    confidence: ThreatConfidence = ThreatConfidence.HIGH
    source: str = "active_defense"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FirewallRule:
    """An OS firewall rule (iptables/pf)."""
    rule_id: str
    chain: FirewallChain
    action: FirewallRuleAction
    protocol: Optional[str] = None
    source_ip: Optional[str] = None
    source_port: Optional[int] = None
    dest_ip: Optional[str] = None
    dest_port: Optional[int] = None
    interface: Optional[str] = None
    comment: str = ""
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    priority: int = 100
    active: bool = True


@dataclass
class WAFRule:
    """A WAF rule."""
    rule_id: str
    zone_id: str
    description: str
    expression: str
    action: WAFRuleMode
    priority: int = 1
    enabled: bool = True
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    cloudflare_rule_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ThreatIntelligence:
    """What is known about an address at a network edge."""
    intel_id: str
    ip_address: str
    reputation_score: float  # 0.0 clean .. 1.0 highly malicious
    confidence: ThreatConfidence
    sources: List[ThreatIntelSource]
    threat_types: List[AttackType]
    first_seen: float
    last_seen: float
    report_count: int = 0
    country: Optional[str] = None
    asn: Optional[int] = None
    isp: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DDoSAttackMetrics:
    """Distributed denial-of-service readings at a network edge."""
    requests_per_second: float
    unique_ips: int
    bandwidth_mbps: float
    connection_count: int
    syn_flood_rate: float
    udp_flood_rate: float
    http_flood_rate: float
    average_packet_size: float
    top_source_countries: List[Tuple[str, int]]
    detection_threshold_exceeded: bool
    attack_duration_seconds: float
    estimated_botnet_size: int


@dataclass
class DefenseMetrics:
    """What a defence at a network edge has done."""
    total_blocks: int = 0
    active_blocks: int = 0
    temporary_blocks: int = 0
    permanent_blocks: int = 0
    attacks_detected: int = 0
    attacks_mitigated: int = 0
    ddos_attacks_blocked: int = 0
    blocks_by_type: Dict[AttackType, int] = field(default_factory=dict)
    blocks_by_country: Dict[str, int] = field(default_factory=dict)
    firewall_rules_active: int = 0
    waf_rules_active: int = 0
    avg_detection_time_ms: float = 0.0
    avg_response_time_ms: float = 0.0
    false_positive_rate: float = 0.0
    start_time: float = field(default_factory=lambda: datetime.now().timestamp())
    last_update: float = field(default_factory=lambda: datetime.now().timestamp())


# What a system being defended is, and asks for — carried from the security
# vocabulary for the tools that describe the systems they defend.

class SecurityLevel(Enum):
    """How confidential something is."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    TOP_SECRET = "top_secret"


class ContentType(Enum):
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    CODE = "code"
    DATA = "data"


class ContentCategory(Enum):
    ILLEGAL_DRUGS = "illegal_drugs"
    VIOLENCE = "violence"
    ILLEGAL_ACTIVITIES = "illegal_activities"
    CONFIDENTIAL_INFO = "confidential_info"
    PII_DATA = "pii_data"
    SYSTEM_EXPLOITS = "system_exploits"
    MALICIOUS_CODE = "malicious_code"


class ValidationResult(Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    SANITIZED = "sanitized"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class SecurityContext:
    """Who and what a request to a defended system concerns."""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    operation: Optional[str] = None
    data_sensitivity: SecurityLevel = SecurityLevel.INTERNAL
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    content_type: Optional[str] = None
    content_length: int = 0
    request_count: int = 0
    last_activity: float = field(default_factory=lambda: datetime.now().timestamp())


@dataclass
class SecurityPolicy:
    """What a defended system requires of the requests it takes."""
    security_level: SecurityLevel = SecurityLevel.INTERNAL
    max_input_length: int = 10000
    max_output_length: int = 50000
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000
    enable_content_filtering: bool = True
    enable_pii_detection: bool = True
    enable_illegal_content_blocking: bool = True
    content_strictness_multiplier: float = 1.0
    enable_injection_detection: bool = True
    enable_path_traversal_detection: bool = True
    enable_response_sanitization: bool = True
    require_authentication: bool = True
    session_timeout: int = 86400
    max_concurrent_sessions: int = 10
    log_all_operations: bool = True
    log_security_events: bool = True
    alert_on_threats: bool = True
    allowed_operations: List[str] = field(default_factory=list)
    blocked_patterns: List[str] = field(default_factory=list)
    allowed_file_types: List[str] = field(default_factory=lambda: [".txt", ".md", ".py", ".js", ".json"])


@dataclass
class SecurityMetrics:
    """What a defended system's security has counted."""
    total_requests: int = 0
    blocked_requests: int = 0
    sanitized_responses: int = 0
    threats_detected: int = 0
    threats_by_type: Dict[str, int] = field(default_factory=dict)
    critical_threats: int = 0
    content_filtered: int = 0
    illegal_content_blocked: int = 0
    pii_detected: int = 0
    confidential_breaches: int = 0
    average_response_time: float = 0.0
    system_uptime: float = 0.0


# ── THE SENSE ───────────────────────────────────────────────────────────────

#: How a felt threat maps onto the risk vocabulary appraisal already speaks
#: (`_RISK` in appraisal.py: low .2 / medium .5 / high .8 / critical .95).
#: Stated here so the two cannot drift into different scales.
_LEVELS: Tuple[Tuple[float, str], ...] = (
    (0.85, "critical"), (0.55, "high"), (0.25, "medium"), (0.0, "low"))

#: What each kind of meeting weighs, before decay. These are JUDGEMENTS and are
#: written down so they can be argued with.
#:
#: An integrity finding outranks everything: it means the thing doing the
#: judging is not what it was. A refusal is the system WORKING — the act was
#: stopped — so it raises alertness without implying the substrate is under
#: attack, and weighs least.
_WEIGHT: Dict[str, float] = {
    "integrity": 1.00,   # the governing machinery was changed
    "screen": 0.55,      # an argument shaped to escape where it was going
    "refusal": 0.25,     # its own law stopped an act
}

#: A threat felt now matters more than one felt an hour ago. Half-life, seconds.
#: Not zero and not forever: a substrate that forgets instantly cannot notice a
#: pattern, and one that never forgets stays afraid of something that stopped.
_HALF_LIFE_S = 900.0

#: A pattern is made of the attacks still being felt: older than this, an event
#: no longer counts toward one.
_PATTERN_WINDOW_S = 2 * _HALF_LIFE_S


@dataclass(frozen=True)
class ThreatEvent:
    """One thing the substrate met that bears on its own safety."""
    kind: str
    subject: str
    detail: str
    weight: float
    attack: Optional[AttackType] = None
    confidence: Optional[ThreatConfidence] = None
    at: float = field(default_factory=time.monotonic)
    wall: float = field(default_factory=time.time)


class ThreatSense:
    """The substrate's own sense of how threatened it is, and by what."""

    #: Kept bounded: this is a FEELING, not an audit store. The durable record
    #: of what was judged and refused lives in `unified.safety_assessments`.
    MAX_EVENTS = 200
    MAX_INCIDENTS = 50

    def __init__(self) -> None:
        self._events: Deque[ThreatEvent] = deque(maxlen=self.MAX_EVENTS)
        self._incidents: Deque[IncidentReport] = deque(maxlen=self.MAX_INCIDENTS)
        self.perceived = 0
        self.perception_faults = 0

    # ── 1. MEETING IT ─────────────────────────────────────────────────────
    async def note(self, kind: str, subject: str, detail: str = "", *,
                   attack: Optional[AttackType] = None,
                   confidence: Optional[ThreatConfidence] = None,
                   weight: Optional[float] = None) -> Optional[ThreatEvent]:
        """The substrate met something that bears on its safety.

        Routed through the PERCEPTION door rather than recorded here, so it
        becomes a memory and a belief like anything else the substrate meets —
        which is the difference between feeling threatened and holding a number.
        A perception failure never loses the feeling: the event is kept either
        way and the failure is counted."""
        kind = str(kind or "").strip().lower()
        if kind not in _WEIGHT and weight is None:
            logger.error("threat sense: %r is not a kind of threat this "
                         "substrate knows how to feel", kind)
            return None
        event = ThreatEvent(kind=kind, subject=str(subject),
                            detail=str(detail),
                            weight=float(_WEIGHT.get(kind, weight or 0.0)),
                            attack=attack, confidence=confidence)
        self._events.append(event)
        what = attack.value if attack is not None else kind
        try:
            from core.domain.evidence_producers import submit_perception
            from core.memory import Origin
            await submit_perception(
                "threat_sense", "security_event",
                {"component": f"{what}:{event.subject}"[:120],
                 "severity": self.level_name(),
                 "message": event.detail or f"{what} concerning {event.subject}"},
                domain="substrate_safety", origin=Origin.own("threat sense"))
            self.perceived += 1
        except Exception as error:
            self.perception_faults += 1
            logger.error("threat sense: %s concerning %s was FELT but not "
                         "perceived (no memory, so nothing can be believed "
                         "about it): %s", what, event.subject, error)
        return event

    def record_incident(self, report: IncidentReport) -> None:
        """What the Constitution did about what was met. Kept for reporting;
        the durable account is the Constitution's containment log."""
        self._incidents.append(report)

    # ── 2. FEELING IT ─────────────────────────────────────────────────────
    def level(self) -> Optional[float]:
        """How threatened this substrate is, in [0,1]. None when nothing is felt.

        None is not zero. A substrate that has met nothing is not SAFE, it is
        UNTESTED, and reporting 0.0 would feed appraisal a measured calm it
        never measured."""
        if not self._events:
            return None
        now = time.monotonic()
        total = 0.0
        for event in self._events:
            age = max(0.0, now - event.at)
            total += event.weight * (0.5 ** (age / _HALF_LIFE_S))
        # SATURATING, not averaging. Ten screen faults are worse than one, and
        # nothing is worse than certain.
        return min(1.0, total)

    def dominant(self) -> Optional[ThreatEvent]:
        """WHICH event the felt level is mostly made of, or None when nothing
        is felt.

        `level()` answers HOW threatened; this answers ABOUT WHAT. The dominant
        event is the largest DECAYED contributor, which is the same arithmetic
        `level()` sums — so what the substrate says it is worried about is, by
        construction, what is actually driving the worry. Ties break toward the
        more recent event."""
        if not self._events:
            return None
        now = time.monotonic()

        def live(event: ThreatEvent) -> Tuple[float, float]:
            age = max(0.0, now - event.at)
            return event.weight * (0.5 ** (age / _HALF_LIFE_S)), event.at

        return max(self._events, key=live)

    # ── 3. KNOWING WHAT IT IS ─────────────────────────────────────────────
    def patterns(self) -> List[AttackPattern]:
        """The attacks met more than once and still being felt, most frequent
        first. An attack met once is an event; met again, it is a pattern."""
        now = time.monotonic()
        groups: Dict[AttackType, List[ThreatEvent]] = {}
        for event in self._events:
            if event.attack is None or now - event.at > _PATTERN_WINDOW_S:
                continue
            groups.setdefault(event.attack, []).append(event)
        found: List[AttackPattern] = []
        for attack, events in groups.items():
            if len(events) < 2:
                continue
            worst = max((e.confidence for e in events if e.confidence is not None),
                        key=lambda c: list(ThreatConfidence).index(c),
                        default=ThreatConfidence.MEDIUM)
            found.append(AttackPattern(
                pattern_id=f"{attack.value}:{int(events[0].wall)}",
                attack_type=attack, signature=attack.value,
                indicators=[e.subject for e in events],
                frequency=len(events), severity=Severity(worst.value),
                first_detected=events[0].wall, last_detected=events[-1].wall,
                affected_endpoints=sorted({e.subject for e in events}),
                mitigation_applied=any(i.attack_type is attack and i.blocked
                                       for i in self._incidents)))
        return sorted(found, key=lambda p: p.frequency, reverse=True)

    def level_name(self) -> str:
        """The felt level in appraisal's own risk vocabulary."""
        felt = self.level()
        if felt is None:
            return "low"
        for floor, name in _LEVELS:
            if felt >= floor:
                return name
        return "low"

    def status(self) -> Dict[str, Any]:
        felt = self.level()
        recent = list(self._events)[-5:]
        met = self.dominant()
        about = None
        if met is not None:
            about = f"{(met.attack.value if met.attack else met.kind)}:{met.subject}"
        return {
            "felt": None if felt is None else round(felt, 4),
            "level": None if felt is None else self.level_name(),
            "about": about,
            "events": len(self._events),
            "perceived": self.perceived,
            "perception_faults": self.perception_faults,
            "patterns": [p.to_dict() for p in self.patterns()],
            "incidents": [i.to_dict() for i in list(self._incidents)[-5:]],
            "recent": [{"kind": e.kind,
                        "attack": e.attack.value if e.attack else None,
                        "confidence": e.confidence.value if e.confidence else None,
                        "subject": e.subject, "detail": e.detail[:80]}
                       for e in recent],
        }
