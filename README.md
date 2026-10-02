# Sports Match Intelligence

Sports-event dashboard for cricket, badminton, tennis, football, boxing, rugby, F1, golf, table tennis and basketball.

## Sources
- https://www.cricinfo.com/
- https://www.premierleague.com/en/
- https://www.chinaopen.com/en/
- https://www.skysports.com/
- https://www.espn.in/

## Setup

1. Open **Settings → Secrets and variables → Actions**.
2. Add a repository secret named **FIRECRAWL_API_KEY**. Never put the key in the HTML or repository.
3. Open **Settings → Pages** and choose **GitHub Actions** as the source.
4. Open **Actions → Scrape sports and deploy → Run workflow** once.

The workflow runs every 3 hours. It extracts structured events with Firecrawl, normalizes them into `data/matches.json`, and deploys the static dashboard.

## Architecture

Sources → Firecrawl → normalized JSON → GitHub Pages dashboard.
