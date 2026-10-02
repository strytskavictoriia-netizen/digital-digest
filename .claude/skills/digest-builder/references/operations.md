# Running things locally

## Python environment

The repo needs Python 3.11+. On Windows the `python` command is often missing — use the `py` launcher:

```bash
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt     # Windows
.venv/bin/python -m pip install -r requirements.txt             # macOS / Linux
```

Then run everything as `.venv/Scripts/python.exe -m digest <command>` from the repo root.
On Windows set `PYTHONIOENCODING=utf-8` (or the code's own reconfigure handles it) so Ukrainian
text prints correctly.

## `.env`

Copy `.env.example` to `.env`. The user fills in tokens themselves. Check what is filled without
revealing values, e.g.:

```bash
grep -n "^[A-Z_]*=" .env | sed -E 's/=(.{0,6}).+/=\1…(заповнено)/'
```

## Calling Claude from a local run (dry-run)

The engine calls the Claude Code CLI (`claude -p`) with `CLAUDE_CODE_OAUTH_TOKEN`.

- If `claude` is not on PATH, set `CLAUDE_CLI="npx -y @anthropic-ai/claude-code"`.
- **When you (Claude Code) run the digest from inside your own session**, your environment contains
  session variables (`CLAUDE_CODE_*`, `ANTHROPIC_*`) that break the child CLI's authentication.
  Unset them for the command:
  ```bash
  unset $(env | grep -oE "^(ANTHROPIC|CLAUDE)[A-Z_]*") && CLAUDE_CLI="npx -y @anthropic-ai/claude-code" .venv/Scripts/python.exe -m digest daily --dry-run
  ```
  (`load_dotenv` then supplies `CLAUDE_CODE_OAUTH_TOKEN` from `.env`.)
- A generation takes 2–5 minutes — run it in the background and wait for it.
- Quick token check (costs almost nothing):
  ```bash
  CLAUDE_CODE_OAUTH_TOKEN=<from .env> npx -y @anthropic-ai/claude-code -p "Відповідай одним словом: ок" --model claude-sonnet-5
  ```
  `401 OAuth access token is invalid` → see troubleshooting (usually the token was created in the
  wrong terminal or copied incompletely).

## Git

The user's repo was created from the template; you commit and push changes to `config.yaml`,
`archive/`, `state/`. On some Windows drives git complains about "dubious ownership" — fix with
`git config --global --add safe.directory '<path>'`. Pushing uses the user's Git Credential Manager
login (a browser window may open the first time).

## Reading GitHub Actions status

If the `gh` CLI is installed and logged in, use it (`gh run list`, `gh run view --log`). Otherwise
read-only API calls with the stored git credential work:

```bash
TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
curl -s -H "Authorization: Bearer $TOKEN" https://api.github.com/repos/<owner>/<repo>/actions/runs?per_page=5
```

Never print the token. Starting runs (`workflow_dispatch`) is a visible action — ask first.
