"""Safe display-text cleanup shared by public renderers."""

from __future__ import annotations

import re
from html import escape

FORMULA_STYLE = (
    "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
    "font-size:0.95em;background:#f8fafc;border:1px solid #e2e8f0;"
    "border-radius:4px;padding:1px 4px;white-space:nowrap;"
)
LATEX_MACRO_PATTERN = re.compile(r"\\(?P<name>[A-Za-z]+)(?P<args>(?:\{[^{}]*\})+)")


def clean_display_text(value: str) -> str:
    """Normalize common extracted TeX noise without changing meaning."""

    text = value.replace("~", " ")
    text = text.replace("\\%", "%")
    text = re.sub(r"\\\((.*?)\\\)", r"\1", text)
    text = re.sub(r"\$(.*?)\$", r"\1", text)
    text = re.sub(r"\${2,}", "", text)
    text = _clean_latex_macros(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_display_text(value: str) -> str:
    """Escape prose and wrap conservative formula-like spans for display."""

    text = _preclean_formula_text(value)
    explicit_pattern = re.compile(r"\\\((.*?)\\\)|\$([^$\n]{1,120})\$")
    formulas: list[str] = []

    def replace_explicit(match: re.Match[str]) -> str:
        formula = match.group(1) if match.group(1) is not None else match.group(2)
        if match.group(2) is not None and not _looks_like_formula(formula or ""):
            return match.group(0)
        formulas.append(_formula_span(formula or ""))
        return f"@@RR_FORMULA_{len(formulas) - 1}@@"

    with_placeholders = explicit_pattern.sub(replace_explicit, text)
    formatted = _format_implicit_formulas(escape(with_placeholders))
    for index, formula in enumerate(formulas):
        formatted = formatted.replace(f"@@RR_FORMULA_{index}@@", formula)
    return formatted


def _preclean_formula_text(value: str) -> str:
    text = value.replace("~", " ")
    text = text.replace("\\%", "%")
    text = re.sub(r"\${2,}", "", text)
    text = text.replace("\\times", "×").replace("\\Delta", "∆")
    text = _clean_latex_macros(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _looks_like_formula(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if re.search(r"[=^_{}\\]|[κλθ∆×]", text):
        return True
    if re.search(r"[A-Za-z0-9]\s*/\s*[A-Za-z0-9]", text):
        return True
    if re.fullmatch(r"[A-Za-z]\s+\d+(?:\.\d+)?", text):
        return True
    if re.search(r"[A-Za-z]\([A-Za-z0-9, _+\-]{0,30}\)", text):
        return True
    return False


def _format_implicit_formulas(html: str) -> str:
    formula_pattern = re.compile(
        r"(?<![A-Za-z0-9_-])("
        r"[A-Za-z]\([A-Za-z0-9, _+\-]{0,30}\)\s*=\s*"
        r"[A-Za-z0-9κλθ+\-*/^{}().]+"
        r"|[A-Za-z]\([A-Za-z0-9, _+\-]{0,30}\)"
        r"|\d+(?:\.\d+)?×"
        r"|[κλθ]\s*=\s*\d+(?:\.\d+)?"
        r")(?![A-Za-z0-9_-])"
    )
    return formula_pattern.sub(lambda match: _formula_span(match.group(1)), html)


def _formula_span(value: str) -> str:
    formula = _preclean_formula_text(value)
    if not formula:
        return ""
    return f'<span class="rr-formula" style="{FORMULA_STYLE}">{escape(formula)}</span>'


def _clean_latex_macros(value: str) -> str:
    def replace_macro(match: re.Match[str]) -> str:
        name = match.group("name").casefold()
        arguments = re.findall(r"\{([^{}]*)\}", match.group("args"))
        if name in {"frac", "dfrac", "tfrac"} and len(arguments) >= 2:
            result = f"{arguments[0]}/{arguments[1]}"
            return " ".join([result, *arguments[2:]])
        return " ".join(arguments)

    text = LATEX_MACRO_PATTERN.sub(replace_macro, value)
    return re.sub(r"\\([A-Za-z]+)", r"\1", text)
