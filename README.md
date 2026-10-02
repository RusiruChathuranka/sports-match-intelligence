# Sports Match Intelligence

A calendar-first sports-event intelligence dashboard covering **cricket, badminton, tennis, football, boxing, rugby, F1, golf, table tennis and basketball**.

## Primary sources requested

- Cricket — ESPNcricinfo
- Football — Sky Sports Football Scores & Fixtures
- Rugby — Sky Sports Rugby Union Fixtures
- F1 — Sky Sports F1 Schedule
- Tennis — Sky Sports Tennis Scores & Schedule

The full-month inventory is enriched with SofaScore's public scheduled-event feeds so the dashboard can capture lower-profile leagues and sports that are not fully exposed by the requested pages.

## What the dashboard does

- Shows **Today / Tomorrow / This Month / Next 7 Days** counts.
- Shows exact event **date + time** when the provider supplies a timestamp.
- Uses **Time TBD** rather than inventing a time when a provider only supplies a date.
- Lets you switch the event table between **Today, Next 7 Days and Entire Month**.
- Searches teams, players, competitions and sports.
- Exports the normalized inventory as CSV.
- Stores normalized data in `data/matches.json`.
- Deduplicates the same event across providers.

## Setup

1. Open **Settings → Pages** and keep **GitHub Actions** selected as the source.
2. Open **Actions → Scrape sports and deploy → Run workflow** once.
3. The workflow refreshes the full target month every 6 hours.

### Optional Firecrawl

The current calendar pipeline does **not require a Firecrawl key**. It uses direct public schedule/score feeds for the monthly inventory. Firecrawl can be added later as an extraction/validation layer for pages that do not expose structured data.

## Target month

The scraper defaults to the runner's current month. To force a month, set the environment variable:

`TARGET_MONTH=2026-10`

This is useful for rebuilding the complete October 2026 inventory.

## Data architecture

Requested sports sites + public schedule feeds → normalized events → deduplication → `data/matches.json` → GitHub Pages dashboard.
