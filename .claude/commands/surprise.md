---
description: Log something surprising (good or bad) that happened while building, to ledger/decisions.md
argument-hint: "[optional: what happened]"
---

Log a surprise to `ledger/decisions.md`.

Ask me these **one at a time**. If `$ARGUMENTS` is non-empty, use it as the answer to question 1 and skip it. If the surprise just happened in this conversation, propose a pre-filled answer I can confirm.

1. What happened?
2. Was it good or bad, and why did it matter?

Append (never rewrite earlier entries) in exactly this format, using the current local time from `date "+%Y-%m-%d %H:%M %Z"`:

```markdown
## [SURPRISE] 2026-10-23 17:05 IST — <short title>

- **What happened:** ...
- **Good or bad:** good|bad — ...
```

Create the file with a `# Decisions log` heading if it does not exist. Keep my wording. Confirm with the entry's title.
