"""
MEM Summit 2026 Presentation Scraper
Scrapes PDF presentations from endpointsummit2026.sched.com

Phase 1 (Playwright, visible browser): bypass Cloudflare, collect session
        links, find PDF URLs on each session page.
Phase 2 (requests): download PDFs directly using cookies grabbed from the
        browser session — fast, no browser overhead per file.
"""

import asyncio
import re
import sys
import time
from pathlib import Path

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://endpointsummit2026.sched.com"
OUTPUT_DIR = Path(__file__).parent / "presentations"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180]


async def wait_for_cloudflare(page, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        title = await page.title()
        if "just a moment" not in title.lower() and "cloudflare" not in title.lower():
            return True
        await asyncio.sleep(1)
    return False


async def get_session_links(page) -> list[str]:
    print(f"Opening {BASE_URL} ...")
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    await wait_for_cloudflare(page)
    await page.wait_for_timeout(2000)

    print("Scrolling to load all sessions...")
    for _ in range(20):
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(300)

    links = await page.eval_on_selector_all(
        "a[href]",
        "els => els.map(el => el.href).filter(h => h.includes('/event/'))",
    )
    unique = list(dict.fromkeys(links))
    print(f"Found {len(unique)} session links.")
    return unique


async def find_presentation_links(page, session_url: str) -> list[dict]:
    try:
        await page.goto(session_url, wait_until="domcontentloaded", timeout=30000)
        await wait_for_cloudflare(page)
        await page.wait_for_timeout(600)
    except PlaywrightTimeoutError:
        print(f"  Timeout: {session_url}")
        return []

    title = ""
    try:
        title = (await page.title()).split(" - ")[0].strip()
    except Exception:
        pass

    candidates = await page.eval_on_selector_all(
        "a[href]",
        """els => els.map(el => ({ href: el.href, text: el.innerText.trim() }))
                      .filter(o =>
                          o.href.toLowerCase().includes('.pdf') ||
                          o.href.toLowerCase().includes('.pptx') ||
                          o.href.toLowerCase().includes('.ppt') ||
                          o.href.toLowerCase().includes('/files/') ||
                          o.text.toLowerCase().includes('download') ||
                          o.text.toLowerCase().includes('slides') ||
                          o.text.toLowerCase().includes('presentation'))""",
    )

    # Strip "Modern Management Summit YYYY" (or similar) prefix from title
    clean_title = re.sub(r'^[^:_]+[:_]\s*', '', title).strip() if title else ""

    results = []
    for link in candidates:
        href = link.get("href", "")
        if not href or href.startswith("javascript"):
            continue
        # Preserve the actual file extension from the URL
        lower = href.lower().split("?")[0]
        if lower.endswith(".pptx"):
            ext = ".pptx"
        elif lower.endswith(".ppt"):
            ext = ".ppt"
        else:
            ext = ".pdf"
        fname = sanitize_filename(clean_title or "session") + ext
        results.append({"url": href, "filename": fname})

    return results


def download_with_requests(
    session: requests.Session, url: str, dest: Path
) -> bool:
    if dest.exists():
        print(f"  Already exists: {dest.name}")
        return True
    try:
        resp = session.get(url, stream=True, timeout=60, allow_redirects=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        size_kb = dest.stat().st_size // 1024
        print(f"  Saved ({size_kb} KB): {dest.name}")
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        return False


async def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"PDFs will be saved to: {OUTPUT_DIR.resolve()}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=UA,
            accept_downloads=True,
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        # ── Phase 1a: collect session links ───────────────────────────────────
        session_links = await get_session_links(page)
        if not session_links:
            print("No session links found.")
            await browser.close()
            return

        # ── Phase 1b: find PDF links on each session page ─────────────────────
        all_pdfs: list[dict] = []
        print("\nScanning session pages for PDFs...")
        for i, link in enumerate(session_links, 1):
            pdfs = await find_presentation_links(page, link)
            new_pdfs = [p for p in pdfs if not (OUTPUT_DIR / p["filename"]).exists()]
            skipped = len(pdfs) - len(new_pdfs)
            if new_pdfs:
                print(f"[{i}/{len(session_links)}] {link}")
                print(f"  -> {len(new_pdfs)} new PDF(s) found")
                all_pdfs.extend(new_pdfs)
            elif skipped:
                print(f"[{i}/{len(session_links)}] already downloaded, skipping")
            await page.wait_for_timeout(400)

        if not all_pdfs:
            print("\nNo PDFs found.")
            await browser.close()
            return

        print(f"\nTotal PDFs to download: {len(all_pdfs)}")

        # ── Grab browser cookies for the requests session ─────────────────────
        cookies = await context.cookies()
        await browser.close()

    # ── Phase 2: download via requests (fast, no browser overhead) ────────────
    http = requests.Session()
    http.headers["User-Agent"] = UA
    for c in cookies:
        http.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

    print("\nDownloading PDFs...\n")
    succeeded = failed = 0
    for pdf in all_pdfs:
        dest = OUTPUT_DIR / pdf["filename"]
        print(f"Downloading: {pdf['filename']}")
        ok = download_with_requests(http, pdf["url"], dest)
        if ok:
            succeeded += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Done.  Downloaded: {succeeded}   Failed: {failed}")
    print(f"Files saved to: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
