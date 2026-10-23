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

## [CHECKPOINT] 2026-10-23 17:59 IST — Phase 3: agla-mcp server

- **Session cost:** n/a (status line does not run in VS Code) (session 456b20f1)

## [CHECKPOINT] 2026-10-23 18:47 IST — Phase 4: Telegram bot (quotes, UPI link, demo tickets, stats, language choice)

- **Session cost:** n/a (status line does not run in VS Code) (session 456b20f1)

## [OVERRIDE] 2026-10-23 19:05 IST — Runtime model stays Sonnet 5.5 after the station-parsing eval

- **Question:** Which model should the bot run on after the Phase 5 station-parsing eval?
- **Options:** (1) switch to Haiku 5.5 now (plan.md rule: Haiku if it matches Sonnet's accuracy); (2) switch to Haiku after a quick reply-quality check in English, Hinglish and Hindi; (3) stay on Sonnet 5.5.
- **Claude suggested:** Option 2. Both models scored 50/50 (Haiku ~19x cheaper: $0.19 vs $3.62 per 1k messages; 3.24 s vs 3.90 s median), but the eval only measures parsing, not reply quality.
- **Chose:** Option 3, stay on Sonnet 5.5, and keep the eval results on record.
- **Why:** Sonnet's replies are already tested on the phone; the recorded eval is what we'd use to revisit the choice if we scale up.

## [CHECKPOINT] 2026-10-23 19:07 IST — Phase 5: station-parsing eval (Sonnet vs Haiku, 50/50 both; resolver fixes)

- **Session cost:** n/a (status line does not run in VS Code) (session 456b20f1)

## [DECISION] 2026-10-23 19:19 IST — Metro Miles recalibrated: 1/km, +25 new station, +10 streak

- **Question:** plan.md's rules (5 miles/km, +50 new station, +20 streak) gave the demo commuter ~10k miles a month, five free day passes. How generous should Metro Miles be?
- **Options:** (A) keep plan.md's rules; (B) 2/km, +50, +20 (~4.8k/month); (C) 1/km, +25, +10 (~2.4k/month); (D) 1/km, +20, +5 (~2.2k/month); or keep A and raise reward costs ~4x. Simulated on the seeded month.
- **Claude suggested:** C.
- **Chose:** C. 2x off-peak and +10 safe arrival unchanged.
- **Why:** All day passes was too generous; C gives a heavy commuter about one day pass or a few chais a month.

## [CHECKPOINT] 2026-10-23 19:24 IST — Phase 6: badges and Metro Miles (calibrated rules, rewards, demo seed)

- **Session cost:** n/a (status line does not run in VS Code) (session 456b20f1)
