---
description: Record a one-line status with session cost in ledger/decisions.md, then commit everything
argument-hint: "[optional: one-line status]"
allowed-tools: Bash(git add:*), Bash(git commit:*), Bash(git status:*), Bash(git push:*), Bash(date:*), Bash(cat:*)
---

Create a checkpoint.

1. If `$ARGUMENTS` is non-empty, use it as the status. Otherwise ask me for a one-line status, suggesting one based on what we just finished.
2. Read the session cost from `ledger/.session_cost.json` (written by the status line). If the file is missing or the cost is null, write `cost: n/a`.
3. Append to `ledger/decisions.md` (create it with a `# Decisions log` heading if missing), using the local time from `date "+%Y-%m-%d %H:%M %Z"`:

   ```markdown
   ## [CHECKPOINT] 2026-10-23 17:05 IST — <status>

   - **Session cost:** $1.23 (session <first 8 chars of session id>)
   ```

4. Run `git status --short` and check that no `.env` or other secret file is staged. If one would be, stop and tell me.
5. Run `git add -A && git commit -m "checkpoint: <status>"` and end the message with a trailer naming your current model, e.g. `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
6. If a remote named `origin` exists, run `git push`. If not, say so and don't create one.
7. Reply with the short commit hash and the status.
