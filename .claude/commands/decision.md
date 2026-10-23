---
description: Log a build decision (DECISION, or OVERRIDE if I went against Claude's suggestion) to ledger/decisions.md
argument-hint: "[optional: the question being decided]"
---

Log a decision to `ledger/decisions.md`.

Ask me these **one at a time**, waiting for each answer before asking the next. If `$ARGUMENTS` is non-empty, use it as the answer to question 1 and skip it. If the decision was just discussed in this conversation, propose a pre-filled answer for each question so I can reply "yes" or correct it.

1. What was the question being decided?
2. What options were considered?
3. What did Claude suggest?
4. What did I choose?
5. Why?

Tag the entry `OVERRIDE` if my choice differs from Claude's suggestion, otherwise `DECISION`.

Append (never rewrite earlier entries) in exactly this format, using the current local time from `date "+%Y-%m-%d %H:%M %Z"`:

```markdown
## [DECISION] 2026-10-23 17:05 IST — <short title>

- **Question:** ...
- **Options:** ...
- **Claude suggested:** ...
- **Chose:** ...
- **Why:** ...
```

Create the file with a `# Decisions log` heading if it does not exist. Keep my wording and only tidy grammar. Confirm with the entry's title and tag.
