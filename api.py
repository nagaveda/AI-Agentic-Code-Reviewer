import hashlib
import hmac
import json

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from config import GITHUB_WEBHOOK_SECRET
from graph import ReviewState, get_graph

app = FastAPI(title="AI Code Reviewer")


class ReviewRequest(BaseModel):
    pr_url: str


def _run_review(pr_url: str) -> dict:
    graph = get_graph()
    initial: ReviewState = {
        "pr_url": pr_url,
        "diff": {},
        "bug_findings": [],
        "security_findings": [],
        "style_findings": [],
        "final_findings": [],
        "review_posted": False,
    }
    result = graph.invoke(initial)
    return {
        "findings": result["final_findings"],
        "total": len(result["final_findings"]),
        "posted": result["review_posted"],
    }


@app.post("/review")
def review(req: ReviewRequest) -> dict:
    return _run_review(req.pr_url)


def _verify_signature(payload: bytes, signature: str) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook")
async def github_webhook(request: Request) -> dict:
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not _verify_signature(payload_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return {"status": "ignored", "reason": f"event={event}"}

    data = json.loads(payload_bytes)
    action = data.get("action", "")
    if action not in ("opened", "reopened"):
        return {"status": "ignored", "reason": f"action={action}"}

    pr_url = data["pull_request"]["html_url"]
    return _run_review(pr_url)
