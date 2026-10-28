"""Recover structured data from Pydantic ``str(model)`` text.

Older versions of the investigation decorator stored some results (GitFive,
VK, DNS recon) as ``str(model)`` - e.g. ``username='x' repos=[Repo(name='y')]``.
This turns such text back into dicts/lists using a *safe* AST walk: only
literals, ``Name(k=v, ...)`` constructors and a few known wrappers are accepted;
nothing is ever executed.
"""
import ast
import io
import re
import tokenize
from typing import Any, Optional

_FIELD_START = re.compile(r"^[A-Za-z_]\w*=")


class _Unsupported(Exception):
    pass


def _to_call_source(text: str) -> str:
    """``a=1 b=[X(c=2)]`` -> ``__root__(a=1, b=[X(c=2)])`` (commas between top-level fields)."""
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    out, depth, prev_end = [], 0, None
    for i, tok in enumerate(tokens):
        if tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER):
            continue
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth -= 1
        is_field = (
            depth == 0 and tok.type == tokenize.NAME and i + 1 < len(tokens)
            and tokens[i + 1].type == tokenize.OP and tokens[i + 1].string == "="
        )
        if is_field and out:
            out.append(", ")
        elif prev_end is not None and tok.start != prev_end:
            out.append(" ")
        out.append(tok.string)
        prev_end = tok.end
    return "__root__(" + "".join(out) + ")"


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in ("None", "True", "False"):
            return {"None": None, "True": True, "False": False}[node.id]
        raise _Unsupported(node.id)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_eval(e) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {str(_eval(k)): _eval(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in ("datetime", "date"):
            parts = [_eval(a) for a in node.args[:6]]
            stamp = "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts[:3]))
            if len(parts) > 3:
                stamp += "T" + ":".join(f"{p:02d}" for p in parts[3:6])
            return stamp
        if node.keywords:
            return {kw.arg: _eval(kw.value) for kw in node.keywords if kw.arg}
        if len(node.args) == 1:  # HttpUrl('...'), Decimal('1.0'), ...
            return _eval(node.args[0])
        if not node.args:
            return {}
        raise _Unsupported(name)
    raise _Unsupported(type(node).__name__)


def parse_model_repr(text: Any) -> Optional[dict]:
    """Return a dict for ``str(model)`` text, or None if it doesn't look like one."""
    if not isinstance(text, str) or not _FIELD_START.match(text.strip()):
        return None
    try:
        tree = ast.parse(_to_call_source(text.strip()), mode="eval")
        value = _eval(tree.body)
    except (SyntaxError, ValueError, TypeError, _Unsupported, tokenize.TokenError, RecursionError):
        return None
    return value if isinstance(value, dict) and value else None
