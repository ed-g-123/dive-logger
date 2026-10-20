# Dive Log Dashboard

A static diving logbook dashboard that merges **PADI** (JSON export) and **Oceanic+** (UDDF)
logs into one unified `data/merged_log.json`, served on GitHub Pages.

## How it works

1. Drop files into `data/`:
   - `data/padi/*.json` — PADI logbook JSON export
   - `data/oceanic/*.uddf` — Oceanic+ UDDF export (whole history every time is fine)
2. Run `python3 scripts/merge.py` (stdlib only, no dependencies) — or let GitHub Actions
   run it automatically on every push (`.github/workflows/build.yml`).
3. Open `index.html` (or your `https://<user>.github.io/<repo>/` URL).

Merging: Oceanic+ wins for stats/depth profile; PADI wins for site names, buddies, notes.
Same dive in both = same date + max depth within 3 m.

## Map positions for PADI dives

PADI exports carry a site name but no coordinates. Add the name to `data/site_coords.json`:

```json
{ "Sandals Negril": { "lat": 18.3332, "lon": -78.338 } }
```

`merge.py` applies it to PADI dives and lists any site names still missing a position.
The current "Sandals Negril" entry is borrowed from your "Sandals Beach" site; replace it
with the exact position. PADI dives are all treated as air, and PADI times of day are ignored.

## Flagged dives and trips

- Scuba records under 5 minutes are flagged (`suspect: true`), shown faded, and left out of totals.
- Dives are grouped into trips (a gap of more than 7 days starts a new trip); the page shows trip chips.

## Editing site names

Oceanic+ site names are opaque hashes (`site_6ad4de…`). On first run the merge script
guesses a region name from coordinates and writes `data/site_aliases.json`.
**Edit that file** to put real site names in ("Blue Hole", "The Canyon", …) and re-run
the merge — your edits persist because known ids are never overwritten.

## Known Oceanic+ quirks (handled by the merge script)

| Quirk | Handling |
|---|---|
| Temperatures in Kelvin (302.44) | Converted to °C (29.3) |
| Tank pressure in Pascal (2.2E7) | Converted to bar (220) |
| Malformed offsets (`+00:03` = UTC+3) | Offset dropped; local wall time kept |
| Site names are hashes | `data/site_aliases.json` mapping |
| Apnoe entries are snorkel sessions | Kept, tagged `dive_mode: "apnoe"`, filterable |

## Privacy

If the repo is **public**, anyone can see your dive sites and dates (plus coordinates
in this README-adjacent data). Make the repo private (GitHub Pro required for private
Pages), or strip coordinates in `scripts/merge.py` before committing.

## Dev locally

Any static server works: `python3 -m http.server` then open http://localhost:8000
(fetching JSON over file:// is blocked by browsers).
