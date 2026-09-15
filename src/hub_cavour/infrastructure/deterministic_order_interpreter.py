"""Exact-match deterministic interpreter for the first palmare demonstration."""

from __future__ import annotations

from collections.abc import Mapping

from hub_cavour.application.order_intake import (
    ClarificationCode,
    ClarificationIssue,
    InterpretationResult,
    normalize_reference,
)


class DeterministicOrderInterpreter:
    """Return configured interpretations without catalog knowledge or guessing."""

    def __init__(self, rules: Mapping[str, InterpretationResult]) -> None:
        self._rules: dict[str, InterpretationResult] = {}
        for text, result in rules.items():
            normalized = normalize_reference(text)
            if not normalized:
                raise ValueError("Interpreter rule text cannot be empty")
            if normalized in self._rules:
                raise ValueError("Interpreter rules must be unique after normalization")
            self._rules[normalized] = result

    def interpret(self, text: str) -> InterpretationResult:
        normalized = normalize_reference(text)
        result = self._rules.get(normalized)
        if result is not None:
            return result
        return InterpretationResult(
            intent=None,
            issues=(
                ClarificationIssue(
                    ClarificationCode.UNSUPPORTED_INPUT,
                    text,
                    "The deterministic interpreter has no exact rule for this input",
                ),
            ),
        )
