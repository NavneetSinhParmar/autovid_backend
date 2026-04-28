import re
from typing import Any


_DOUBLE_BRACE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_SINGLE_BRACE_RE = re.compile(r"\{(?!\{)\s*([^{}]+?)\s*\}(?!\})")
_BARE_SCOPED_TOKEN_RE = re.compile(r"\b(customer|company)\.([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)


def _normalize_path(path: str) -> list[str]:
    """
    Supports:
      - customer.full_name
      - customer?.full_name  (optional chaining style)
      - company?.logo_url
      - custom_text1
    """
    path = str(path).strip()
    # normalize optional chaining tokens: customer?.x -> customer.x
    path = path.replace("?.", ".")
    path = path.strip(".")
    return [p for p in path.split(".") if p]


def _resolve_path(path: str, context: dict[str, Any]) -> str:
    cur: Any = context
    for key in _normalize_path(path):
        if isinstance(cur, dict):
            # exact match first
            if key in cur:
                cur = cur[key]
                continue
            # case-insensitive fallback
            kl = key.lower()
            found = False
            for k, v in cur.items():
                if str(k).lower() == kl:
                    cur = v
                    found = True
                    break
            if found:
                continue
        return ""
    if cur is None:
        return ""
    return str(cur)


def replace_placeholders(text: str, context: dict[str, Any]) -> str:
    """
    Replaces placeholders in both formats:
      - {{customer.full_name}}
      - {customer.full_name}
      - {custom_text1}

    Missing keys resolve to empty string.
    """
    if not isinstance(text, str) or not text:
        return "" if text is None else str(text)

    # Support legacy "flat" placeholders like {{logoUrl}} by promoting keys from
    # customer/company to the top-level (without overriding explicit values).
    ctx: dict[str, Any] = dict(context or {})
    for scope in ("customer", "company"):
        scoped = ctx.get(scope)
        if not isinstance(scoped, dict):
            continue
        for k, v in scoped.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float)) and k not in ctx:
                ctx[k] = v
            # common camelCase aliases used by some templates
            if k == "logo_url" and "logoUrl" not in ctx:
                ctx["logoUrl"] = v
            if k == "company_name" and "companyName" not in ctx:
                ctx["companyName"] = v
            if k == "customer_company_name" and "customerCompanyName" not in ctx:
                ctx["customerCompanyName"] = v

    def _double(match: re.Match) -> str:
        return _resolve_path(match.group(1), ctx)

    def _single(match: re.Match) -> str:
        return _resolve_path(match.group(1), ctx)

    out = _DOUBLE_BRACE_RE.sub(_double, text)
    out = _SINGLE_BRACE_RE.sub(_single, out)

    # Support templates that mistakenly use bare tokens like "customer.full_name"
    # (without braces). We only replace scoped tokens to avoid accidental changes.
    def _bare_scoped(match: re.Match) -> str:
        scope = match.group(1)
        key = match.group(2)
        # keep original casing of scope out of it; resolver is case-insensitive anyway
        return _resolve_path(f"{scope}.{key}", ctx)

    out = _BARE_SCOPED_TOKEN_RE.sub(_bare_scoped, out)
    return out

