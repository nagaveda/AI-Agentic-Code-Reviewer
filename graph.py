import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents import run_bug_detector, run_critic, run_security_scanner, run_style_analyzer
from mcp_server import fetch_pr_diff, post_github_review

log = logging.getLogger(__name__)


class ReviewState(TypedDict):
    pr_url: str
    diff: dict
    bug_findings: Annotated[list, operator.add]
    security_findings: Annotated[list, operator.add]
    style_findings: Annotated[list, operator.add]
    final_findings: list
    review_posted: bool


# ── graph nodes ──────────────────────────────────────────────────────────────

def fetch_diff_node(state: ReviewState) -> dict:
    log.info("[fetch_diff]      fetching PR diff for %s", state["pr_url"])
    diff = fetch_pr_diff(state["pr_url"])
    files = diff.get("files", [])
    additions = sum(f["additions"] for f in files)
    deletions = sum(f["deletions"] for f in files)
    log.info("[fetch_diff]      %d file(s), +%d -%d lines — dispatching 3 agents", len(files), additions, deletions)
    return {"diff": diff}


def dispatch_to_agents(state: ReviewState) -> list[Send]:
    return [
        Send("bug_detector", state),
        Send("security_scanner", state),
        Send("style_analyzer", state),
    ]


def bug_detector_node(state: ReviewState) -> dict:
    findings = run_bug_detector(state["diff"])
    return {"bug_findings": findings}


def security_scanner_node(state: ReviewState) -> dict:
    findings = run_security_scanner(state["diff"])
    return {"security_findings": findings}


def style_analyzer_node(state: ReviewState) -> dict:
    findings = run_style_analyzer(state["diff"])
    return {"style_findings": findings}


def critic_node(state: ReviewState) -> dict:
    final = run_critic(
        state.get("bug_findings", []),
        state.get("security_findings", []),
        state.get("style_findings", []),
    )
    return {"final_findings": final}


def post_review_node(state: ReviewState) -> dict:
    findings = state["final_findings"]
    log.info("[post_review]     posting %d finding(s) to GitHub...", len(findings))
    result = post_github_review(state["pr_url"], findings)
    inline = result.get("inline_count", 0)
    log.info("[post_review]     done — %d inline comment(s), %d as review body", inline, len(findings) - inline)
    return {"review_posted": result.get("posted", False)}


# ── graph construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    builder = StateGraph(ReviewState)

    builder.add_node("fetch_diff", fetch_diff_node)
    builder.add_node("bug_detector", bug_detector_node)
    builder.add_node("security_scanner", security_scanner_node)
    builder.add_node("style_analyzer", style_analyzer_node)
    builder.add_node("critic", critic_node)
    builder.add_node("post_review", post_review_node)

    builder.add_edge(START, "fetch_diff")
    builder.add_conditional_edges("fetch_diff", dispatch_to_agents)
    builder.add_edge("bug_detector", "critic")
    builder.add_edge("security_scanner", "critic")
    builder.add_edge("style_analyzer", "critic")
    builder.add_edge("critic", "post_review")
    builder.add_edge("post_review", END)

    return builder.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
