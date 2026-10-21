# Dive Log Dashboard

A static, multi-diver dive-log dashboard for GitHub Pages. Python (standard library only) turns each
diver's exports into one `data/merged_log.json`; the page (Leaflet map, Plotly profile) just reads it.

Divers: **EG** (Oceanic+ UDDF + PADI) and **RA** (Shearwater Cloud + PADI, to be added).

## Folder layout

```
data/
  divers.json                  who is in the log, colours, and what is public
  divers/EG/oceanic/*.uddf     Oceanic+ UDDF exports (the whole history each time is fine)
  divers/EG/padi/*.json        PADI logbook exports
  divers/RA/shearwater/*.json  slim extracts made from Shearwater Cloud (never the raw .db)
  divers/RA/padi/*.json        RA's PADI exports: just drop them in
  site_aliases.json            Oceanic+ site ids -> readable names (your edits are kept)
  site_coords.json             site name -> lat/lon, for dives with no position
  trip_defaults.json           fallback position for a diver's unpositioned dives on a trip
  clocks.json                  what clock each Shearwater trip/day used (utc or local) and the zone offset
  trips.json                   your named trips (id, name, start, end); other dives are grouped automatically
  links.json                   manual overrides for shared dives
  review.json                  (generated) possible shared dives that need a decision
  merged_log.json              (generated) what the page reads
pipeline/                      adapters, merge, link, publish, build
tests/                         python3 -m unittest discover -s tests
private/                       raw device files; git-ignored, never uploaded
```

## Everyday use

1. Put new files in the diver's folder (GitHub web upload is fine). The workflow runs the tests, rebuilds
   `merged_log.json` and commits it; or run `python3 -m pipeline.build` locally.
2. Open the site, or locally `python3 -m http.server` and http://localhost:8000.

### Adding RA's Shearwater dives

Keep the raw `.db` in `private/RA/shearwater/`. It holds a device serial, UUIDs, exact timestamps, resort names,
buddy and notes, and its file name contains an email address. Then:

```
python3 -m pipeline.extract_shearwater private/RA/shearwater/shearwater_cloud.db RA
```

This writes `data/divers/RA/shearwater/extracted.json`: depth, duration, gas, temperature, a 10 s profile, start time
to the minute and the site name. Venue, buddy and notes are left out unless you add `--keep venue,buddy,notes`.

## How the data is combined

1. **Per diver:** device dives (Oceanic+ or Shearwater) are matched to that diver's PADI entries (same date,
   depth within 3 m). The device wins numbers, profile and time; PADI wins site and title and fills empty fields.
2. **Between divers:** a dive both divers did stays as two records joined by a `group`. They are linked when depth
   (2.5 m) and duration (7 min) agree and the clock difference is a whole number of hours (devices differ in
   time zone). A trip-wide clock offset separates back-to-back dives. Unsure pairs go to `data/review.json`.
   Override in `data/links.json`: `{"link": [["EG:uddf:...", "RA:sw:..."]], "unlink": [[...]]}`.
3. A linked dive is drawn once on the map and shows both profiles on one chart; gaps (site name, position) are
   filled from the partner record, never overwritten.
4. **Trips:** dives inside a range in `data/trips.json` join that named trip (all divers); the rest are grouped automatically (a gap of
   more than 7 days starts a new trip, id like `2026-10`). Use the trip ids from `trips.json` as the keys in `clocks.json` and
   `trip_defaults.json` (`RA:tulum-2024`); they don't change when dives are added.

## Assumptions

- PADI entries are treated as **air**; PADI time of day is ignored (date only).
- Oceanic+ start times are local time (the offset is written as hours in the minutes slot, `-00:05` = UTC-5).
- Shearwater start times have no time zone: on some trips the device clock was UTC, on others it was already local.
  `data/clocks.json` says which, per diver and trip, so the page can show local times:
  `{"RA:2026-10": {"clock": "utc", "tz_offset_h": -5}}` converts UTC to local; `{"RA:2023-10": {"clock": "local"}}` keeps the
  time. Trips not listed stay UTC and are labelled "UTC" on the page. To check a trip, compare a shared dive's Shearwater
  time with the Oceanic+ time: 0 minutes apart means the clock was local; the zone offset apart means UTC.
- Scuba records under 5 minutes are flagged, shown faded and left out of totals. Freedives are kept but not counted as scuba.
- Oceanic+ quirks handled: Kelvin temperatures, malformed offsets (`-00:05` = UTC-5), site ids as names, samples past the end of the dive.

## Privacy

`data/divers.json` sets what is published per diver (`time_of_day`, `buddies`, `notes`, `venue`, `profile`,
`temperature`, `links`). RA's defaults are strict: no time of day, buddies, notes or venue. Hiding `links` for a
diver removes the shared-dive link for both. A free GitHub Pages site is **public**, so get RA's agreement first,
and remember that dive sites and dates are visible to everyone.

## Map positions

Dives without coordinates are listed under the map. Add the site name to `data/site_coords.json`
(`{"Angelita": {"lat": 20.3, "lon": -87.0}}`, matched case-insensitively) and rebuild.
