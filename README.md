# Agla Station

A Telegram bot for the Delhi NCR metro network (DMRC, Rapid Metro Gurugram, Noida Aqua Line): ride more, ride safer, have fun doing it.

> Work in progress. See `plan.md` for the build plan.

## Honest constraints

- Tickets are mock QR tickets. DMRC has no public ticket-issuing API.
- Payment is a UPI intent link; payment is not verified.
- Fares come from official sources and are spot-checked by hand; never invented.
- Journey sharing is an estimate from the timetable, not live GPS.
- Metro Miles and rewards are a concept demo. Vouchers are labelled "demo, not redeemable".
