import json
import logging
import re
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config import ANTHROPIC_API_KEY, MAX_TOKENS, MODEL

logging.basicConfig(format="%(asctime)s  %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger(__name__)

# ── LangChain model ───────────────────────────────────────────────────────────

_llm = ChatAnthropic(
    model=MODEL,
    api_key=ANTHROPIC_API_KEY,
    max_tokens=MAX_TOKENS,
)

_str_parser = StrOutputParser()

# ── prompts ───────────────────────────────────────────────────────────────────

_BUG_SYSTEM = """\
You are a bug detection agent. Analyze the PR diff for software bugs.

Look for:
- Null/None dereference without guards
- Off-by-one errors in loops and array indexing
- Unhandled exceptions and missing error handling
- Functions returning wrong or inconsistent types
- Type mismatches and invalid type coercions

Respond ONLY with a JSON array:
[{{"file": "filename", "line": line_or_null, "severity": "critical|high|medium|low",
  "description": "concise description"}}]

Focus on changed lines (lines starting with +). Return [] if none found.\
"""

_SECURITY_SYSTEM = """\
You are a security vulnerability scanner. Analyze the PR diff for security issues.

Look for:
- Hardcoded secrets, passwords, API keys, or tokens
- SQL injection via string concatenation
- Unsafe deserialization (pickle, yaml.load without Loader)
- Dangerous functions: eval(), exec(), os.system()
- Missing authentication or authorization checks
- Command injection via subprocess with shell=True

Respond ONLY with a JSON array:
[{{"file": "filename", "line": line_or_null, "severity": "high|critical",
  "description": "concise description"}}]

Focus on changed lines. All findings must be high or critical. Return [] if none found.\
"""

_STYLE_SYSTEM = """\
You are a code style and quality analyzer. Analyze the PR diff for style issues.

Look for:
- Functions exceeding 50 lines of code
- Missing docstrings on public functions and classes
- Poor naming (single letters, cryptic abbreviations)
- Dead or unreachable code
- Overly complex logic that could be simplified

Respond ONLY with a JSON array:
[{{"file": "filename", "line": line_or_null, "severity": "low|medium",
  "description": "concise description"}}]

Focus on changed lines. All findings must be low or medium severity. Return [] if none found.\
"""

_CRITIC_SYSTEM = """\
You are a code review critic. Evaluate findings from bug, security, and style agents.

Score each finding's confidence 0.0–1.0:
- 1.0: definite bug or confirmed vulnerability
- 0.8–0.9: very likely issue
- 0.6–0.7: possible issue worth reviewing
- < 0.6: noise — omit it

Deduplicate findings that refer to the same underlying issue (same file, same root cause).
Assign a category: "bug", "security", or "style".

Return ONLY a JSON array:
[{{"file": "filename", "line": line_or_null, "severity": "critical|high|medium|low",
  "description": "concise description", "confidence": 0.85, "category": "bug|security|style"}}]

Include only findings with confidence >= 0.6. No explanations, just the JSON array.\
"""

# ── LangChain LCEL chains (prompt | llm | parser) ────────────────────────────

_bug_chain = (
    ChatPromptTemplate.from_messages([
        ("system", _BUG_SYSTEM),
        ("human", "Analyze this PR diff:\n\n{diff}"),
    ])
    | _llm
    | _str_parser
)

_security_chain = (
    ChatPromptTemplate.from_messages([
        ("system", _SECURITY_SYSTEM),
        ("human", "Analyze this PR diff:\n\n{diff}"),
    ])
    | _llm
    | _str_parser
)

_style_chain = (
    ChatPromptTemplate.from_messages([
        ("system", _STYLE_SYSTEM),
        ("human", "Analyze this PR diff:\n\n{diff}"),
    ])
    | _llm
    | _str_parser
)

_critic_chain = (
    ChatPromptTemplate.from_messages([
        ("system", _CRITIC_SYSTEM),
        ("human", "Evaluate and score these findings:\n\n{findings}"),
    ])
    | _llm
    | _str_parser
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _format_diff(diff: dict) -> str:
    parts = []
    for f in diff.get("files", []):
        parts.append(f"### {f['filename']} (+{f['additions']} -{f['deletions']})")
        if f["patch"]:
            parts.append(f["patch"])
    return "\n".join(parts)


def _extract_json(text: str) -> list:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


def _log_reply(label: str, text: str) -> None:
    preview = text.replace("\n", " ").strip()
    if len(preview) > 120:
        preview = preview[:120] + "…"
    log.info("  %s claude reply: %s", label, preview)


def _log_findings(label: str, findings: list[dict]) -> None:
    for f in findings:
        loc = f"{f.get('file', '?')}:{f.get('line', '?')}"
        log.info(
            "  %s   [%-8s] %-30s  %s",
            label,
            f.get("severity", "?"),
            loc,
            f.get("description", "")[:70],
        )

# ── agent functions ───────────────────────────────────────────────────────────

def run_bug_detector(diff: dict) -> list[dict]:
    files = diff.get("files", [])
    log.info("[bug_detector]    → sending %d file(s) to Claude via LangChain (%s)", len(files), MODEL)
    raw = _bug_chain.invoke({"diff": _format_diff(diff)})
    _log_reply("[bug_detector]   ", raw)
    findings = _extract_json(raw)
    log.info("[bug_detector]    ← %d finding(s)", len(findings))
    _log_findings("[bug_detector]   ", findings)
    return findings


def run_security_scanner(diff: dict) -> list[dict]:
    files = diff.get("files", [])
    log.info("[security_scanner] → sending %d file(s) to Claude via LangChain (%s)", len(files), MODEL)
    raw = _security_chain.invoke({"diff": _format_diff(diff)})
    _log_reply("[security_scanner]", raw)
    findings = _extract_json(raw)
    log.info("[security_scanner] ← %d finding(s)", len(findings))
    _log_findings("[security_scanner]", findings)
    return findings


def run_style_analyzer(diff: dict) -> list[dict]:
    files = diff.get("files", [])
    log.info("[style_analyzer]  → sending %d file(s) to Claude via LangChain (%s)", len(files), MODEL)
    raw = _style_chain.invoke({"diff": _format_diff(diff)})
    _log_reply("[style_analyzer] ", raw)
    findings = _extract_json(raw)
    log.info("[style_analyzer]  ← %d finding(s)", len(findings))
    _log_findings("[style_analyzer] ", findings)
    return findings


def run_critic(
    bug_findings: list[dict],
    security_findings: list[dict],
    style_findings: list[dict],
) -> list[dict]:
    all_findings: list[dict[str, Any]] = []
    for f in bug_findings:
        all_findings.append({**f, "category": "bug"})
    for f in security_findings:
        all_findings.append({**f, "category": "security"})
    for f in style_findings:
        all_findings.append({**f, "category": "style"})

    if not all_findings:
        log.info("[critic]          no findings to score — skipping")
        return []

    log.info("[critic]          → scoring %d raw finding(s) via LangChain (%s)...", len(all_findings), MODEL)
    raw = _critic_chain.invoke({"findings": json.dumps(all_findings, indent=2)})
    _log_reply("[critic]         ", raw)
    final = _extract_json(raw)
    filtered = len(all_findings) - len(final)
    log.info("[critic]          ← %d passed, %d filtered out (confidence < 0.6)", len(final), filtered)
    for f in final:
        log.info(
            "  [critic]            [%-8s] conf=%.2f  %-30s  %s",
            f.get("severity", "?"),
            f.get("confidence", 0),
            f"{f.get('file', '?')}:{f.get('line', '?')}",
            f.get("description", "")[:60],
        )
    return final
