# MEM Summit 2026 Presentation Scraper

Automatically downloads all PDF and PowerPoint presentations from the [MEM Summit 2026 schedule](https://endpointsummit2026.sched.com/).

## How it works

1. **Phase 1 – Browser scan**: Opens a visible Chromium browser to bypass Cloudflare protection, scrolls through the schedule page to load all sessions, then visits each session page to find presentation download links.
2. **Phase 2 – Download**: Downloads all found files directly using `requests` (fast, no browser overhead). Already-downloaded files are skipped automatically on re-runs.

Files are saved to a `presentations/` subfolder, named after the session title.

## Requirements

- Python 3.10+
- Install dependencies:

```bash
pip install playwright requests
playwright install chromium
```

## Usage

```bash
python scraper.py
```

A browser window will open — **do not close it**. If a Cloudflare challenge appears, it will resolve automatically within 30 seconds. Once the scan is complete the browser closes itself and downloads begin.

## Notes

- **Re-run safe**: already downloaded files are detected by filename and skipped.
- **Cloudflare**: the script uses a visible (non-headless) browser with the `webdriver` flag hidden to pass bot checks.
- **403 errors**: a small number of files may return 403 — these are access-restricted by the presenter and require a logged-in sched.com account to download manually.
- Supported formats: `.pdf`, `.pptx`, `.ppt`
