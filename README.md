# AI Code Reviewer

A multi-agent code review system that analyzes GitHub pull requests and posts structured inline comments back via the GitHub Review API.

## Architecture

```
POST /review
     │
     ▼
fetch_diff ──► [bug_detector │ security_scanner │ style_analyzer] (parallel)
                                       │
                                       ▼
                                    critic  (scores & filters)
                                       │
                                       ▼
                                  post_review  (GitHub Review API)
```

| Component | Role |
|-----------|------|
| `mcp_server.py` | FastMCP server — `fetch_pr_diff`, `post_github_review`, `run_static_analysis` |
| `agents.py` | Four Claude-powered agents: BugDetector, SecurityScanner, StyleAnalyzer, Critic |
| `graph.py` | LangGraph state machine — parallel fan-out via `Send()` API |
| `api.py` | FastAPI — `POST /review` and `POST /webhook` endpoints |

## Setup

### 1. Prerequisites

- Python 3.11+
- A GitHub personal access token with `repo` scope
- An Anthropic API key

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
GITHUB_WEBHOOK_SECRET=   # optional — only needed for /webhook
```

### 4. Run the API server

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

### 5. Trigger a review

```bash
curl -X POST http://localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{"pr_url": "https://github.com/owner/repo/pull/123"}'
```

Response:

```json
{
  "findings": [
    {
      "file": "src/auth.py",
      "line": 42,
      "severity": "critical",
      "description": "Hardcoded API key",
      "confidence": 0.97,
      "category": "security"
    }
  ],
  "total": 1,
  "posted": true
}
```

## GitHub Webhook

Set your webhook URL to `https://<your-host>/webhook` with:

- **Content type**: `application/json`
- **Secret**: the value of `GITHUB_WEBHOOK_SECRET`
- **Events**: Pull requests (opened, reopened)

The server validates `X-Hub-Signature-256` before processing. If `GITHUB_WEBHOOK_SECRET` is empty, signature validation is skipped.

## MCP Server (standalone)

The MCP server can also run as a standalone MCP server for use with other MCP clients:

```bash
python mcp_server.py
```

Tools exposed:

| Tool | Description |
|------|-------------|
| `fetch_pr_diff` | Returns per-file patches, PR title, and body |
| `post_github_review` | Posts inline review comments via GitHub Review API |
| `run_static_analysis` | Runs pylint on a code snippet and returns output |

## Notes

- All LLM calls use `claude-sonnet-4-5`. Change `MODEL` in `config.py` to switch models.
- Findings with critic confidence < 0.6 are filtered out before posting.
- If a finding lacks a file path or line number, it is posted as a general review comment rather than an inline comment.
- The server is synchronous — no async agents or streaming.
