"""Rule conditions as data (never eval'd).

    {"all": [cond, ...]}  {"any": [cond, ...]}  {"not": cond}
    {"field": "amount", "op": "<=", "value": 50000000}

Ops: == != < <= > >= in not_in. Numbers compare as Decimal so money is exact.
An empty condition ({} or {"all": []}) always matches.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.errors import AppError

OPS = ("==", "!=", "<", "<=", ">", ">=", "in", "not_in")
OP_LABELS = {
    "==": "=",
    "!=": "≠",
    "<": "<",
    "<=": "≤",
    ">": ">",
    ">=": "≥",
    "in": "salah satu dari",
    "not_in": "bukan salah satu dari",
}


def _num(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | Decimal):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return None


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op in ("in", "not_in"):
        values = expected if isinstance(expected, list) else [expected]
        hit = actual in values or str(actual) in {str(v) for v in values}
        return hit if op == "in" else not hit
    a, e = _num(actual), _num(expected)
    left: Any = a if a is not None and e is not None else actual
    right: Any = e if a is not None and e is not None else expected
    if op == "==":
        return bool(left == right)
    if op == "!=":
        return bool(left != right)
    if left is None or right is None:
        return False
    try:
        return bool(
            {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]
        )
    except TypeError:
        return False


def evaluate(cond: dict[str, Any] | None, ctx: dict[str, Any]) -> bool:
    if not cond:
        return True
    if "all" in cond:
        return all(evaluate(c, ctx) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, ctx) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], ctx)
    return _compare(ctx.get(cond["field"]), cond["op"], cond.get("value"))


def validate(cond: dict[str, Any] | None) -> None:
    """Reject malformed conditions before they are stored."""
    if not cond:
        return
    if not isinstance(cond, dict):
        raise AppError("INVALID_CONDITION", "Format kondisi tidak valid.")
    for key in ("all", "any"):
        if key in cond:
            if not isinstance(cond[key], list):
                raise AppError("INVALID_CONDITION", f"'{key}' harus berupa daftar kondisi.")
            for c in cond[key]:
                validate(c)
            return
    if "not" in cond:
        validate(cond["not"])
        return
    if not isinstance(cond.get("field"), str) or not cond["field"]:
        raise AppError("INVALID_CONDITION", "Setiap kondisi wajib punya nama field.")
    if cond.get("op") not in OPS:
        raise AppError("INVALID_CONDITION", f"Operator '{cond.get('op')}' tidak dikenal.")


def describe(cond: dict[str, Any] | None) -> str:
    """Human-readable Bahasa Indonesia text, e.g. 'amount ≤ 50.000.000'."""
    if not cond:
        return "Semua"
    if "all" in cond:
        parts = [describe(c) for c in cond["all"]]
        return " dan ".join(parts) if parts else "Semua"
    if "any" in cond:
        return "(" + " atau ".join(describe(c) for c in cond["any"]) + ")"
    if "not" in cond:
        return "bukan " + describe(cond["not"])
    value = cond.get("value")
    num = _num(value)
    shown = (
        f"{num:,.0f}".replace(",", ".") if num is not None and num == num.to_integral() else value
    )
    if isinstance(value, list):
        shown = ", ".join(str(v) for v in value)
    return f"{cond['field']} {OP_LABELS.get(cond['op'], cond['op'])} {shown}"
