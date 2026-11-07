"""
Declarative, Explainable Confluence Scoring Cards & Decision Traces.

Adapted from investing-algorithm-framework (IAF) architecture to replace
fragile imperative if/else trading logic with structured, auditable decision engines.

Core Components:
1. Composable Operators: GT, GTE, LT, LTE, EQ, NEQ, BETWEEN, CROSS_ABOVE, CROSS_BELOW.
2. Composable Logical Expressions: Condition, AllOf, AnyOf, Not, AtLeast.
3. Scoring & Veto Tiers: PrimaryGroup (entry trigger), SecondaryGroup (weighted evidence), VetoGroup (hard disqualifiers).
4. ConfluenceCard: High-level declarative setup definition.
5. DecisionTrace: Flat, JSON-serializable audit trail explaining why every trade was executed, sized down, or vetoed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class Operator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"
    BETWEEN = "between"
    CROSS_ABOVE = "cross_above"
    CROSS_BELOW = "cross_below"


@dataclass(frozen=True)
class EvaluationContext:
    """Current and prior bar indicator values provided by a strategy or bar series."""

    values: Mapping[str, Any]
    previous_values: Mapping[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def previous(self, name: str, default: Any = None) -> Any:
        return self.previous_values.get(name, default)


class Expression:
    """Base class for composable logical expressions."""

    def evaluate(self, context: EvaluationContext) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class Condition(Expression):
    """A declarative comparison between an indicator and a scalar value or reference indicator."""

    indicator: str
    operator: Operator | str
    value: Any = None
    reference: Optional[str] = None
    name: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.operator, Operator):
            object.__setattr__(self, "operator", Operator(str(self.operator).lower()))
        if not self.indicator:
            raise ValueError("Condition indicator name must not be empty.")
        if self.reference is not None and self.value is not None:
            raise ValueError("Condition accepts either 'value' or 'reference', not both.")
        if self.operator is Operator.BETWEEN:
            if not isinstance(self.value, (tuple, list)) or len(self.value) != 2:
                raise ValueError("BETWEEN operator requires value tuple (low, high).")
            object.__setattr__(self, "value", tuple(self.value))

    def evaluate(self, context: EvaluationContext) -> bool:
        lhs = context.get(self.indicator)
        if lhs is None:
            return False

        rhs = context.get(self.reference) if self.reference is not None else self.value
        if rhs is None and self.operator not in (Operator.EQ, Operator.NEQ):
            return False

        try:
            if self.operator is Operator.GT:
                return lhs > rhs
            if self.operator is Operator.GTE:
                return lhs >= rhs
            if self.operator is Operator.LT:
                return lhs < rhs
            if self.operator is Operator.LTE:
                return lhs <= rhs
            if self.operator is Operator.EQ:
                return lhs == rhs
            if self.operator is Operator.NEQ:
                return lhs != rhs
            if self.operator is Operator.BETWEEN:
                low, high = self.value
                return low <= lhs <= high

            # Sequential transition operators (require previous values)
            prev_lhs = context.previous(self.indicator)
            prev_rhs = context.previous(self.reference) if self.reference is not None else self.value
            if prev_lhs is None or prev_rhs is None:
                return False

            if self.operator is Operator.CROSS_ABOVE:
                return prev_lhs <= prev_rhs and lhs > rhs
            if self.operator is Operator.CROSS_BELOW:
                return prev_lhs >= prev_rhs and lhs < rhs
        except (TypeError, ValueError):
            return False

        return False


@dataclass(frozen=True)
class AllOf(Expression):
    """Evaluates True only if all child expressions evaluate True."""

    expressions: tuple[Expression, ...]

    def __init__(self, *expressions: Expression) -> None:
        if not expressions:
            raise ValueError("AllOf requires at least one child expression.")
        object.__setattr__(self, "expressions", expressions)

    def evaluate(self, context: EvaluationContext) -> bool:
        return all(expr.evaluate(context) for expr in self.expressions)


@dataclass(frozen=True)
class AnyOf(Expression):
    """Evaluates True if any child expression evaluates True."""

    expressions: tuple[Expression, ...]

    def __init__(self, *expressions: Expression) -> None:
        if not expressions:
            raise ValueError("AnyOf requires at least one child expression.")
        object.__setattr__(self, "expressions", expressions)

    def evaluate(self, context: EvaluationContext) -> bool:
        return any(expr.evaluate(context) for expr in self.expressions)


@dataclass(frozen=True)
class Not(Expression):
    """Inverts the boolean evaluation of the child expression."""

    expression: Expression

    def evaluate(self, context: EvaluationContext) -> bool:
        return not self.expression.evaluate(context)


@dataclass(frozen=True)
class AtLeast(Expression):
    """Evaluates True if at least minimum count of child expressions evaluate True."""

    minimum: int
    expressions: tuple[Expression, ...]

    def __init__(self, minimum: int, *expressions: Expression) -> None:
        if minimum < 1 or minimum > len(expressions):
            raise ValueError(f"AtLeast minimum must be between 1 and {len(expressions)}.")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "expressions", expressions)

    def evaluate(self, context: EvaluationContext) -> bool:
        passed = sum(1 for expr in self.expressions if expr.evaluate(context))
        return passed >= self.minimum


# =============================================================================
# SCORING RULES, VETOES & CONFLUENCE CARDS
# =============================================================================

@dataclass(frozen=True)
class ScoreRule:
    """A weighted quantitative rule contributing points toward a confluence score."""

    name: str
    expression: Expression
    weight: float = 10.0
    description: str = ""


@dataclass(frozen=True)
class VetoRule:
    """A hard disqualifier condition. If True, the trade is vetoed immediately."""

    name: str
    expression: Expression
    reason: str = ""


@dataclass(frozen=True)
class PrimaryGroup:
    """Primary setup triggers required to consider a trade."""

    rules: tuple[ScoreRule, ...]
    minimum_matches: int = 1

    def __init__(self, *rules: ScoreRule, minimum_matches: int = 1) -> None:
        if not rules:
            raise ValueError("PrimaryGroup requires at least one rule.")
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "minimum_matches", minimum_matches)


@dataclass(frozen=True)
class SecondaryGroup:
    """Secondary weighted evidence rules contributing to the confluence score."""

    rules: tuple[ScoreRule, ...] = ()
    minimum_score: float = 0.0

    def __init__(self, *rules: ScoreRule, minimum_score: float = 0.0) -> None:
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "minimum_score", minimum_score)


@dataclass(frozen=True)
class VetoGroup:
    """Hard disqualification conditions."""

    rules: tuple[VetoRule, ...] = ()

    def __init__(self, *rules: VetoRule) -> None:
        object.__setattr__(self, "rules", rules)


# =============================================================================
# EXPLAINABLE DECISION TRACE & CONFLUENCE CARD
# =============================================================================

@dataclass
class DecisionTrace:
    """
    Flat, JSON-serializable execution audit trail explaining why every trade
    was executed, sized down, or vetoed.
    """

    card_name: str
    direction: str
    decision: str  # "TRADE_ALLOWED", "VETOED", "INSUFFICIENT_SCORE", "PRIMARY_UNMET"
    trade_allowed: bool
    total_score: float
    max_score: float
    min_required_score: float
    primary_passed: bool
    passed_rules: list[str]
    failed_rules: list[str]
    veto_fired: Optional[str]
    veto_reason: Optional[str]
    context_snapshot: dict[str, Any]
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class ConfluenceCard:
    """
    High-level declarative trading decision engine.

    Evaluates:
    1. VetoGroup (Hard disqualifiers) -> If any fires, trade is immediately VETOED.
    2. PrimaryGroup (Core triggers) -> Must meet minimum_matches.
    3. SecondaryGroup (Confluence evidence) -> Sums weights.
    4. Compares total score against minimum_score -> DecisionTrace.
    """

    def __init__(
        self,
        name: str,
        direction: str = "LONG",
        primary: Optional[PrimaryGroup] = None,
        secondary: Optional[SecondaryGroup] = None,
        vetoes: Optional[VetoGroup] = None,
        min_total_score: float = 50.0,
    ) -> None:
        self.name = name
        self.direction = direction.upper()
        self.primary = primary or PrimaryGroup(ScoreRule("default_primary", Condition("signal", Operator.EQ, True), 50.0))
        self.secondary = secondary or SecondaryGroup()
        self.vetoes = vetoes or VetoGroup()
        self.min_total_score = float(min_total_score)

        # Precalculate max possible score
        primary_max = sum(r.weight for r in self.primary.rules)
        secondary_max = sum(r.weight for r in self.secondary.rules)
        self.max_possible_score = primary_max + secondary_max

    def evaluate(self, context: EvaluationContext) -> DecisionTrace:
        passed_rules: list[str] = []
        failed_rules: list[str] = []
        score = 0.0

        # Step 1: Check Vetoes First (fail-fast)
        for veto in self.vetoes.rules:
            if veto.expression.evaluate(context):
                return DecisionTrace(
                    card_name=self.name,
                    direction=self.direction,
                    decision="VETOED",
                    trade_allowed=False,
                    total_score=0.0,
                    max_score=self.max_possible_score,
                    min_required_score=self.min_total_score,
                    primary_passed=False,
                    passed_rules=[],
                    failed_rules=[],
                    veto_fired=veto.name,
                    veto_reason=veto.reason,
                    context_snapshot=dict(context.values),
                )

        # Step 2: Check Primary Setup Group
        primary_matches = 0
        for rule in self.primary.rules:
            if rule.expression.evaluate(context):
                primary_matches += 1
                score += rule.weight
                passed_rules.append(rule.name)
            else:
                failed_rules.append(rule.name)

        primary_passed = primary_matches >= self.primary.minimum_matches
        if not primary_passed:
            return DecisionTrace(
                card_name=self.name,
                direction=self.direction,
                decision="PRIMARY_UNMET",
                trade_allowed=False,
                total_score=score,
                max_score=self.max_possible_score,
                min_required_score=self.min_total_score,
                primary_passed=False,
                passed_rules=passed_rules,
                failed_rules=failed_rules,
                veto_fired=None,
                veto_reason=None,
                context_snapshot=dict(context.values),
            )

        # Step 3: Check Secondary Confluence Evidence
        for rule in self.secondary.rules:
            if rule.expression.evaluate(context):
                score += rule.weight
                passed_rules.append(rule.name)
            else:
                failed_rules.append(rule.name)

        # Step 4: Final Threshold Check
        trade_allowed = score >= self.min_total_score
        decision = "TRADE_ALLOWED" if trade_allowed else "INSUFFICIENT_SCORE"

        return DecisionTrace(
            card_name=self.name,
            direction=self.direction,
            decision=decision,
            trade_allowed=trade_allowed,
            total_score=score,
            max_score=self.max_possible_score,
            min_required_score=self.min_total_score,
            primary_passed=primary_passed,
            passed_rules=passed_rules,
            failed_rules=failed_rules,
            veto_fired=None,
            veto_reason=None,
            context_snapshot=dict(context.values),
        )
