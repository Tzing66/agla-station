# Decisions log

## [DECISION] 2026-10-23 16:42 IST — Public GitHub repo from the start

- **Question:** Should the GitHub repo be public from the start, private until submission, or local only?
- **Options:** (a) git init + private GitHub repo, made public at submission; (b) git init + public GitHub repo from the start; (c) local git only, no remote.
- **Claude suggested:** No explicit recommendation; listed private-until-submission first and noted that public means the ledger and chats are visible, so scrubbing must be solid.
- **Chose:** git init + public GitHub repo from the start.
- **Why:** (not stated)

## [CHECKPOINT] 2026-10-23 16:47 IST — Phase 0 + 1 done: ledger hooks, slash commands, project skills, architecture agreed

- **Session cost:** n/a (session 456b20f1; status line does not run in VS Code)

## [CHECKPOINT] 2026-10-23 17:38 IST — Phase 2: NCR Network, Routing, Fares

- **Session cost:** n/a (session 456b20f1; status line does not run in VS Code)

## [SURPRISE] 2026-10-23 17:44 IST — Manual spot-check caught a fare bug the automated check missed

- **What happened:** Fare verification against 384 official DMRC fares showed 97.9% matching, but my manual spot-check of 8 pairs in the DMRC app still caught a wrong fare (Kashmere Gate → Noida City Centre: we said ₹43, DMRC charges ₹54). Our straight-line distance was 20.7 km, just under the 21 km slab boundary.
- **Good or bad:** good — the human check found a systematic error (slab-boundary distances) that the automated sample missed, because the random sample rarely landed near a boundary. Shows the spot-check step in the plan earns its place; the fix is noted rather than rushed.

## [CHECKPOINT] 2026-10-23 17:46 IST — Phase 2 follow-up: fare slab limitation documented, spot-check tests

- **Session cost:** n/a (status line does not run in VS Code) (session 456b20f1)
