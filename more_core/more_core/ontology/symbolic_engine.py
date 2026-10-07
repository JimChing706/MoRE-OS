"""Symbolic mathematics engine for L3 reasoning.

Wraps SymPy to provide:
- Expression simplification and evaluation
- Equation solving (single, system, differential)
- Calculus (limits, derivatives, integrals)
- Logical proposition evaluation
- Code-level invariant checking

When SymPy cannot handle a query, the engine returns a descriptive error
rather than raising, so L3 can fall back to LLM-based reasoning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_log = logging.getLogger(__name__)

_TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application, convert_xor)


class SymbolicError(Exception):
    """Raised when symbolic computation fails (caught internally)."""


@dataclass(slots=True)
class SymbolicResult:
    success: bool
    result: Any = None
    error: str = ""
    steps: list[str] = field(default_factory=list)


_EQUATION_SYMBOLS = {"x", "y", "z", "t", "a", "b", "c", "k", "n", "m"}


class SymbolicEngine:
    """Thin wrapper over SymPy for L3 symbolic reasoning."""

    def simplify(self, expression: str) -> SymbolicResult:
        try:
            expr = parse_expr(expression, transformations=_TRANSFORMATIONS)
            simplified = sympy.simplify(expr)
            return SymbolicResult(
                success=True,
                result=str(simplified),
                steps=[f"original: {expression}", f"simplified: {simplified}"],
            )
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    def evaluate(
        self, expression: str, substitutions: dict[str, float] | None = None
    ) -> SymbolicResult:
        try:
            expr = parse_expr(expression, transformations=_TRANSFORMATIONS)
            if substitutions:
                expr = expr.subs(substitutions)
            result = expr.evalf()
            return SymbolicResult(success=True, result=float(result))
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    def solve_equation(self, equation: str, variable: str = "x") -> SymbolicResult:
        try:
            var = sympy.Symbol(variable)
            parsed = parse_expr(equation, transformations=_TRANSFORMATIONS)
            solutions = sympy.solve(parsed, var)
            return SymbolicResult(
                success=True,
                result=[str(s) for s in solutions],
                steps=[f"equation: {equation} = 0", f"solutions: {solutions}"],
            )
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    def solve_system(self, equations: list[str], variables: list[str]) -> SymbolicResult:
        try:
            symbols = [sympy.Symbol(v) for v in variables]
            parsed = [parse_expr(eq, transformations=_TRANSFORMATIONS) for eq in equations]
            solutions = sympy.solve(parsed, symbols, dict=True)
            return SymbolicResult(
                success=True,
                result=[{str(k): str(v) for k, v in sol.items()} for sol in solutions],
                steps=[f"system: {equations}", f"variables: {variables}"],
            )
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    def limit(self, expression: str, variable: str, point: str) -> SymbolicResult:
        try:
            var = sympy.Symbol(variable)
            expr = parse_expr(expression, transformations=_TRANSFORMATIONS)
            pt = (
                sympy.sympify(point)
                if point not in ("oo", "-oo")
                else sympy.oo
                if point == "oo"
                else -sympy.oo
            )
            result = sympy.limit(expr, var, pt)
            return SymbolicResult(
                success=True,
                result=str(result),
                steps=[f"limit of {expression} as {variable}→{point}", f"= {result}"],
            )
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    def differentiate(self, expression: str, variable: str, order: int = 1) -> SymbolicResult:
        try:
            var = sympy.Symbol(variable)
            expr = parse_expr(expression, transformations=_TRANSFORMATIONS)
            deriv = sympy.diff(expr, var, order)
            return SymbolicResult(
                success=True,
                result=str(deriv),
                steps=[f"d^{order}/{variable}^{order} of {expression}", f"= {deriv}"],
            )
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    def integrate(
        self, expression: str, variable: str, limits: tuple[str, str] | None = None
    ) -> SymbolicResult:
        try:
            var = sympy.Symbol(variable)
            expr = parse_expr(expression, transformations=_TRANSFORMATIONS)
            if limits:
                a, b = sympy.sympify(limits[0]), sympy.sympify(limits[1])
                result = sympy.integrate(expr, (var, a, b))
            else:
                result = sympy.integrate(expr, var)
            return SymbolicResult(
                success=True,
                result=str(result),
                steps=[
                    f"∫ {expression} d{variable}"
                    + (f" from {limits[0]} to {limits[1]}" if limits else ""),
                    f"= {result}",
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    def expand(self, expression: str) -> SymbolicResult:
        try:
            expr = parse_expr(expression, transformations=_TRANSFORMATIONS)
            expanded = sympy.expand(expr)
            return SymbolicResult(success=True, result=str(expanded))
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    def factor(self, expression: str) -> SymbolicResult:
        try:
            expr = parse_expr(expression, transformations=_TRANSFORMATIONS)
            factored = sympy.factor(expr)
            return SymbolicResult(success=True, result=str(factored))
        except Exception as exc:  # noqa: BLE001
            return SymbolicResult(success=False, error=str(exc))

    # -- Text-based intent dispatch --------------------------------------------

    def analyse(self, query: str) -> SymbolicResult:
        """Parse a natural-language-style symbolic query and dispatch.
        Supports intent prefixes::

            simplify|s|simp <expr>
            solve <equation> [for <var>]
            system: <eq1>; <eq2>; ... [vars: <v1>, <v2>, ...]
            limit|lim <expr> as <var> -> <point>
            diff|derivative|differentiate <expr> wrt|d <var> [order <n>]
            integrate|integral|int <expr> d<var> [from <a> to <b>]
            expand|factor <expr>
        """
        text = query.strip()

        # simplify
        if text.startswith(("simplify ", "s ", "simp ")):
            expr = text.split(maxsplit=1)[1]
            return self.simplify(expr)

        # solve equation
        if text.startswith("solve "):
            rest = text[6:]
            var = "x"
            if " for " in rest:
                rest, var = rest.rsplit(" for ", 1)
            return self.solve_equation(rest.strip(), var.strip())

        # system of equations
        if text.startswith("system:"):
            parts = text[7:].strip()
            eq_part = parts
            vars_part = "x, y"
            if " vars:" in parts:
                eq_part, vars_part = parts.rsplit(" vars:", 1)
            equations = [e.strip() for e in eq_part.split(";") if e.strip()]
            variables = [v.strip() for v in vars_part.split(",") if v.strip()]
            return self.solve_system(equations, variables)

        # limit
        if text.startswith(("limit ", "lim ")):
            prefix = "limit " if text.startswith("limit ") else "lim "
            rest = text[len(prefix) :]
            if " as " in rest and "->" in rest:
                expr_part, arrow_part = rest.split(" as ", 1)
                var, point = arrow_part.split("->", 1)
                return self.limit(expr_part.strip(), var.strip(), point.strip())

        # differentiate
        if text.startswith(("diff ", "derivative ", "differentiate ")):
            prefixes = ("diff ", "derivative ", "differentiate ")
            for p in prefixes:
                if text.startswith(p):
                    rest = text[len(p) :]
                    break
            order = 1
            if " order " in rest:
                rest, order_part = rest.rsplit(" order ", 1)
                order = int(order_part.strip())
            if " wrt " in rest:
                expr_part, var = rest.split(" wrt ", 1)
            elif " d" in rest and len(rest.split(" d")) == 2:
                expr_part, var = rest.split(" d", 1)
            else:
                return SymbolicResult(
                    success=False,
                    error="cannot parse differentiate: expected 'wrt <var>' or 'd<var>'",
                )
            return self.differentiate(expr_part.strip(), var.strip(), order)

        # integrate
        if text.startswith(("integrate ", "integral ", "int ")):
            prefixes = ("integrate ", "integral ", "int ")
            for p in prefixes:
                if text.startswith(p):
                    rest = text[len(p) :]
                    break
            limits = None
            if " from " in rest and " to " in rest:
                before, after = rest.split(" from ", 1)
                a_str, tail = after.split(" to ", 1)
                b_str = tail.split()[0] if " " in tail else tail
                limits = (a_str.strip(), b_str.strip())
                expr_part = before
                var = after[after.rfind(" d") + 2 :].strip().split()[0] if " d" in after else "x"
            elif " d" in rest:
                expr_part, var = rest.split(" d", 1)
                var = var.strip().split()[0] if var.strip() else "x"
            else:
                return SymbolicResult(
                    success=False, error="cannot parse integral: expected 'd<var>'"
                )
            return self.integrate(expr_part.strip(), var.strip(), limits)

        # expand / factor
        if text.startswith("expand "):
            return self.expand(text[7:])
        if text.startswith("factor "):
            return self.factor(text[6:])

        return SymbolicResult(success=False, error=f"unrecognised symbolic query: {text[:100]}")
