---
name: build-journal
description: Turns this project's process ledger (every prompt, tool call, decision and commit, merged by ledger/build_timeline.py into ledger/timeline.json) into a single self-contained HTML page showing how the project was built - three lanes over time (human prompts, Claude's actions, decisions), milestones, key moments and stats. Use this whenever the user wants the build journal, the process timeline, a page or visual showing how the project was built or how Claude and the human worked together, or wants to refresh or publish it - even if they just say "update the journal", "show the timeline" or "make the process page".
---

# Build journal

The journal is the human-readable view of the process ledger. It answers "how was this built?" for someone who wasn't there: when the human steered, what Claude did, where they disagreed, and how the work moved through the plan.

The page is rendered by a script, not written by hand. The same ledger always gives the same page, and every figure on it comes from the data. Your job is to refresh the data, write a few short annotations, render, and check the result.

## Steps

1. **Refresh the timeline** from the ledger, decisions log, git history and pre-ledger chats:

   ```bash
   python3 ledger/build_timeline.py
   ```

   This writes `ledger/timeline.json` and prints a one-line summary. If it reports unreadable events, mention it to the user, but don't edit `events.jsonl`: the ledger is append-only.

2. **Write or refresh the annotations** in `ledger/journal_notes.json` (format below). Read `ledger/decisions.md` first, because that's where the reasons live. If the file already exists and the user hasn't asked for new wording, keep their edits and only add moments for new decisions, overrides or surprises.

3. **Render the page:**

   ```bash
   python3 .claude/skills/build-journal/scripts/render_journal.py \
       --timeline ledger/timeline.json --notes ledger/journal_notes.json --out docs/build-journal.html
   ```

   If it refuses because a note's number isn't in the data, fix the note, not the check. Either use a placeholder or take the figure from `timeline.json`.

4. **Look at it** in a headless browser at phone (390 px) and desktop width, in light and dark mode. Check that there are no console errors, no horizontal page scroll (the timeline scrolls inside its own box), and that tapping a mark shows its details. Fix layout problems in `assets/template.html`, not in the generated page, so the next render keeps the fix.

5. **Hand over.** Tell the user where the page is and what changed since the last render (new decisions, new phases). The user publishes it. The page is self-contained (no network requests), so it can be opened locally, attached, or published as-is.

## Annotations (`ledger/journal_notes.json`)

```json
{
  "intro": "Two or three plain sentences: what was built, in how long ({elapsed_hours} hours, {active_hours} active), and who did what ({prompts} prompts, {claude_actions} Claude actions).",
  "moments": [
    {"match": "Safety check simplified", "note": "One or two sentences on why this mattered."},
    {"match": "Phase 10", "kind": "checkpoint", "note": "..."}
  ]
}
```

- **`match`** is a case-insensitive piece of a timeline item's title (a decision, checkpoint, commit…). **`kind`** narrows it when a phrase appears more than once (`decision`, `override`, `surprise`, `checkpoint`, `commit`, `prompt`).
- **Placeholders** such as `{prompts}`, `{claude_actions}`, `{active_hours}`, `{elapsed_hours}`, `{overrides}`, or any key of `timeline.json → stats`, are filled in at render time. Use them for figures that grow with the ledger, so the intro never goes stale.
- **Typed numbers** must appear somewhere in `timeline.json`. The renderer checks this, the same rule the product's number guard follows: a journal that misstates its own ledger undermines the point of keeping one.

**What makes a good moment:** overrides (where the human went against Claude's suggestion), surprises, decisions that changed the plan, and the checkpoint where an independent review happened. Six to ten moments is plenty, because the page should show the shape of the build, not retell it.

**How to write them:** plain and factual, in the third person ("the human", "Claude"), with no marketing language. Say what happened and why it mattered, in one or two sentences, using the reasons recorded in `decisions.md` rather than inventing motives. If the user wants the notes in their own voice, they can edit the file directly.

## Files

- `scripts/render_journal.py`: checks the notes and renders the template with the data embedded. Standard library only.
- `assets/template.html`: the page itself (layout, colours, the interactive timeline). Edit this to change how the journal looks. The palette matches the product: marigold and gulabi tints, plum for the human, light and dark.
- `ledger/build_timeline.py` (in the project): builds `timeline.json`. Lanes: `human`, `claude`, `decision`, `milestone`. Long silences (over 30 minutes) are folded on the page, so the timeline shows working time.
