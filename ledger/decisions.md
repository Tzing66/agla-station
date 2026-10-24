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

## [CHECKPOINT] 2026-10-23 19:51 IST — Phase 7: Metro Wrapped (voice skill, pastel card) + off-topic redirects

- **Session cost:** n/a (status line does not run in VS Code) (session 456b20f1)

## [OVERRIDE] 2026-10-23 22:30 IST — Safety check simplified to "I've reached" + share link

- **Question:** The automatic safety check (ask at ETA, nudge, alert trusted contacts; /safety, /trusted invites, /demo_fast) failed its first live test because setup steps weren't obvious. Fix it, park it, or cut it?
- **Options:** (1) fix the setup UX (explicit on/off buttons, status on every ticket, arm for one trip, warnings); (2) park it and move on; (3) cut it down to a traveller-sent "I've reached" message plus the journey share link.
- **Claude suggested:** Option 1 (plan.md lists the safety check under "never cut"); built the UX fixes, 148 tests passing.
- **Chose:** Option 3. Keep 📤 Share journey and a ✅ I've reached button that hands the traveller a ready-made message to send via Telegram's share sheet; remove trusted contacts, invites, timed escalation, the polling job and /demo_fast.
- **Why:** Still didn't like the flow after the fixes; a simple, traveller-controlled "I've reached" is clearer and needs no setup.

## [CHECKPOINT] 2026-10-23 22:35 IST — Phases 8-9: journey sharing + I've reached, dashboard Mini App, button menu

- **Session cost:** n/a (status line does not run in VS Code) (session 456b20f1)

## [CHECKPOINT] 2026-10-23 22:44 IST — Cleanup: remove safety leftovers, refresh docs, README

- **Session cost:** n/a (status line does not run in VS Code) (session 456b20f1)

## [CHECKPOINT] 2026-10-24 09:42 IST — Phase 10: independent review fixes + agla-dev plugin

- **Session cost:** cost: n/a (session 456b20f1)

## [CHECKPOINT] 2026-10-24 10:52 IST — Mini App fix (tunnel watchdog, menu button) + warm redesign and Wrapped as a metro ride

- **Session cost:** cost: n/a (session 456b20f1)

## [DECISION] 2026-10-24 11:53 IST — Metro Wrapped as a three-stop metro ride

- **Question:** How should Metro Wrapped look and feel, now that the pastel card and the Spotify-style story both felt "document-y" or "AI vibe coded"?
- **Options:** (a) Keep the single pastel stats card. (b) A Spotify/Instagram-style story: 10 full-screen slides with progress bars, auto-advance and one big centred number each. (c) A single scrolling poster. (d) A "metro ride": 3 stops (Ride, Places, Rewards) on a route strip in the rider's favourite line colour, with an "Agla station: …" button and left-aligned rows, in the same warm colours.
- **Claude suggested:** First the tap-through story (b) over the scrolling poster, with a warm redesign of the whole Mini App. After feedback, the three-stop metro ride (d), which uses the bot's own "next station" idea in place of Spotify's stock moves, keeps the colours, and computes every figure and "what it means" line in Python.
- **Chose:** The three-stop metro ride (d), in the warm marigold-and-gulabi palette across the whole Mini App, with the colours unchanged. Wrapped stays available all the time for the demo; month-end-only access is parked in the backlog.
- **Why:** The old Wrapped felt "too document-y and not something one would look forward to checking", and the 10-slide story "looks too much like an obvious AI vibe coded attempt at copying Spotify". Fewer, merged screens are easier to get through; the metro-ride idea is specific to Agla Station ("next station"); the warm colours were liked and kept; and short lines explain what each number means without long descriptive text.

## [CHECKPOINT] 2026-10-24 11:53 IST — Log decision: Metro Wrapped as a three-stop metro ride

- **Session cost:** cost: n/a (session 456b20f1)

## [DECISION] 2026-10-24 12:12 IST — DMRC fares: shortest distance plus per-line track factors

- **Question:** How should DMRC fares be calculated so they match the official fares, given that 8 of 384 were off by a slab, including the Kashmere Gate → Noida City Centre spot-check?
- **Options:** (a) Leave it as a documented limitation (known xfail). (b) Fetch new official data, the fare from each line's terminal to every station (~255 requests), to bound real track distances. (c) Use the data we already have: charge DMRC on the shortest track distance between entry and exit, fit per-line track factors to all official fares, widen the "cheapest" search, and check fares on DMRC's own routes.
- **Claude suggested:** Try (c) first because it costs nothing, and fall back to (b) only if one factor per line couldn't fit every official fare. It fit everything with two factors (Magenta ×1.12, Blue ×1.02), so (b) stays as an optional later step to firm up the knife-edge Blue factor.
- **Chose:** Option (c): shortest-distance DMRC pricing, track factors Magenta ×1.12 and Blue ×1.02 in `fares.yaml` (re-checkable with `scripts/fit_track_factors.py`), a wider "cheapest" search, and the fare check on DMRC's own routes. Result: 384/384 official fares match.
- **Why:** "Never invent fares" is the headline rule, so the known misses had to go. The fix uses only official data we already had, needed just two small, explainable corrections (curvy Magenta track; Blue pinned by the spot-check), moves only about 5% of trips by one slab in either direction, and is guarded by tests that run both fare checks. Fetching terminal fares stays available if the Blue factor ever proves wrong.

## [CHECKPOINT] 2026-10-24 12:13 IST — Fares: shortest-distance DMRC pricing + track factors, 384/384 official fares match

- **Session cost:** cost: n/a (session 456b20f1)
