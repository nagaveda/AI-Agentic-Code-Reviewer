import logging
import os
import subprocess
import tempfile
from typing import Any

from fastmcp import FastMCP
from github import Github

from config import GITHUB_TOKEN

log = logging.getLogger(__name__)

mcp = FastMCP("ai-code-reviewer")


def _parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    parts = pr_url.rstrip("/").split("/")
    # https://github.com/{owner}/{repo}/pull/{number}
    pr_number = int(parts[-1])
    repo_name = parts[-3]
    owner = parts[-4]
    return owner, repo_name, pr_number


@mcp.tool()
def fetch_pr_diff(pr_url: str) -> dict[str, Any]:
    """Fetch PR metadata and per-file diffs from GitHub."""
    owner, repo_name, pr_number = _parse_pr_url(pr_url)
    log.info("  [mcp:fetch_pr_diff]  → %s/%s #%d", owner, repo_name, pr_number)

    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(f"{owner}/{repo_name}")
    pr = repo.get_pull(pr_number)
    log.info("  [mcp:fetch_pr_diff]  title: %r", pr.title)

    files = []
    for f in pr.get_files():
        log.info(
            "  [mcp:fetch_pr_diff]  file: %-45s  +%-4d -%d",
            f.filename,
            f.additions,
            f.deletions,
        )
        files.append(
            {
                "filename": f.filename,
                "patch": f.patch or "",
                "additions": f.additions,
                "deletions": f.deletions,
            }
        )

    log.info("  [mcp:fetch_pr_diff]  ← %d file(s) returned", len(files))
    return {
        "files": files,
        "pr_title": pr.title,
        "pr_body": pr.body or "",
    }


@mcp.tool()
def post_github_review(pr_url: str, findings: list[dict]) -> dict[str, Any]:
    """Post review comments to GitHub using the Review API."""
    owner, repo_name, pr_number = _parse_pr_url(pr_url)
    log.info("  [mcp:post_review]    → %s/%s #%d  (%d finding(s))", owner, repo_name, pr_number, len(findings))

    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(f"{owner}/{repo_name}")
    pr = repo.get_pull(pr_number)

    inline_comments = []
    fallback_lines = []

    for finding in findings:
        file_path = finding.get("file")
        line = finding.get("line")
        severity = finding.get("severity", "low").upper()
        description = finding.get("description", "")
        confidence = finding.get("confidence", 1.0)
        category = finding.get("category", "?")
        body_text = f"**[{severity}]** {description} *(confidence: {confidence:.0%})*"

        if file_path and line:
            log.info(
                "  [mcp:post_review]      inline  [%-8s] %-35s line %-4s  %s",
                category,
                file_path,
                line,
                description[:60],
            )
            inline_comments.append(
                {
                    "path": file_path,
                    "line": int(line),
                    "side": "RIGHT",
                    "body": body_text,
                }
            )
        else:
            loc = f"`{file_path}`" if file_path else "general"
            log.info(
                "  [mcp:post_review]      general [%-8s] %s",
                category,
                description[:70],
            )
            fallback_lines.append(f"- {loc}: {body_text}")

    summary_parts = ["## AI Code Review\n"]
    if fallback_lines:
        summary_parts.append("### General findings\n")
        summary_parts.extend(fallback_lines)

    review_body = "\n".join(summary_parts)

    try:
        pr.create_review(body=review_body, event="COMMENT", comments=inline_comments)
        log.info(
            "  [mcp:post_review]    ← posted: %d inline, %d general",
            len(inline_comments),
            len(fallback_lines),
        )
        return {"posted": True, "inline_count": len(inline_comments)}
    except Exception as exc:
        log.warning("  [mcp:post_review]    inline failed (%s) — falling back to body-only", exc)
        plain_lines = [review_body, "\n### Inline findings\n"]
        for c in inline_comments:
            plain_lines.append(f"- `{c['path']}` line {c['line']}: {c['body']}")
        pr.create_review(body="\n".join(plain_lines), event="COMMENT", comments=[])
        log.info("  [mcp:post_review]    ← posted as body-only review")
        return {"posted": True, "inline_count": 0}


@mcp.tool()
def run_static_analysis(code: str, filename: str) -> str:
    """Run pylint on the provided code snippet and return the output."""
    log.info("  [mcp:static_analysis] → pylint on %s (%d lines)", filename, code.count("\n") + 1)
    suffix = os.path.splitext(filename)[1] or ".py"
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["pylint", tmp_path, "--output-format=text", "--score=no"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        log.info("  [mcp:static_analysis] ← %d line(s) of output", len(output.splitlines()))
        return output
    except FileNotFoundError:
        log.warning("  [mcp:static_analysis] pylint not found")
        return "pylint not found — install it with: pip install pylint"
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    mcp.run()
