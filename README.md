# Agla Station

A Telegram bot for the Delhi NCR metro network (DMRC, Rapid Metro Gurugram, Noida Aqua Line): ride more, ride safer, have fun doing it.

> Work in progress. See `plan.md` for the build plan.

## Honest constraints

- Tickets are mock QR tickets. DMRC has no public ticket-issuing API.
- Payment is a UPI intent link; payment is not verified.
- Fares come from official sources and are spot-checked by hand; never invented.
- Journey sharing is an estimate from the timetable, not live GPS.
- Metro Miles and rewards are a concept demo. Vouchers are labelled "demo, not redeemable".

## Known limitations

- **DMRC fares near a slab boundary can be one slab off.** DMRC charges by track distance in slabs (2, 5, 12, 21, 32 km). We approximate track distance by summing straight-line distances between consecutive stations, which under-measures curvy lines. Trips that land within about 1.5 km of a boundary can get the neighbouring slab's fare. Known case from a manual spot-check: Kashmere Gate -> Noida City Centre, we compute 20.7 km (Rs 43) but DMRC charges Rs 54 (over 21 km). Against 384 official fares, 376 match. Planned fix: fit a per-line track-distance factor from official terminal-to-station fares. Details in `data/manual/README.md`.
