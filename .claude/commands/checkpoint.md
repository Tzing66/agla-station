---
description: Record a one-line status in ledger/decisions.md, then commit and push everything
argument-hint: "[optional: one-line status]"
allowed-tools: Bash(git add:*), Bash(git commit:*), Bash(git status:*), Bash(git push:*), Bash(git diff:*), Bash(date:*), Bash(cat:*)
---

Create a checkpoint.

1. If `$ARGUMENTS` is non-empty, use it as the status. Otherwise ask me for a one-line status, suggesting one based on what we just finished.
2. Append to `ledger/decisions.md` (create it with a `# Decisions log` heading if missing), using the local time from `date "+%Y-%m-%d %H:%M %Z"`:

   ```markdown
   ## [CHECKPOINT] 2026-10-23 17:05 IST — <status>
   ```

3. Run `git status --short` and check that no `.env` or other secret file would be committed, and that none of the values in `.env` appear in `git diff` (check without printing them). If either would happen, stop and tell me.
4. Run `git add -A && git commit -m "checkpoint: <status>"` and end the message with a trailer naming your current model, e.g. `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
5. If a remote named `origin` exists, run `git push`. If not, say so and don't create one.
6. Reply with the short commit hash and the status.
