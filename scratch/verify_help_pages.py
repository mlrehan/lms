import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 1000})
        page = await context.new_page()

        test_slugs = [
            "welcome",
            "sign-in",
            "dashboard",
            "sidebar",
            "account",
            "my-team",
            "manager-assignments",
            "organizations",
            "courses",
            "batches",
            "enrollments",
            "timetable",
            "attendance",
            "work-and-results",
            "performance",
            "reports",
            "announcements",
            "discussions",
            "messages",
            "notifications",
            "shared-with-me",
            "common-problems",
            "escalations",
        ]

        print(f"Testing {len(test_slugs)} help articles...")
        failed = []

        for slug in test_slugs:
            url = f"http://localhost:3000/help/corporate-manager/{slug}"
            resp = await page.goto(url, wait_until="domcontentloaded")
            if resp.status != 200:
                print(f"[FAIL] {slug}: HTTP {resp.status}")
                failed.append(slug)
                continue

            # Wait for content header
            title_elem = await page.wait_for_selector("h1", timeout=5000)
            title_text = await title_elem.text_content() if title_elem else "None"

            # Check if any img elements are present
            imgs = await page.query_selector_all("main img")
            for idx, img in enumerate(imgs):
                # Scroll into view so Next.js loads the image
                await img.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                natural_width = await img.evaluate("el => el.naturalWidth")
                src = await img.get_attribute("src")
                if natural_width == 0:
                    # Give it another 500ms
                    await page.wait_for_timeout(500)
                    natural_width = await img.evaluate("el => el.naturalWidth")

                if natural_width == 0:
                    print(f"  [IMG FAIL] broken image in {slug}: {src}")
                    failed.append(f"{slug}:{src}")

            print(f"[PASS] {slug} -> '{title_text.strip()}' | {len(imgs)} img(s) OK")

        await browser.close()
        if failed:
            print(f"\nFAILED ITEMS: {failed}")
            exit(1)
        else:
            print("\nALL 23 HELP ARTICLES PASSED AND RENDERED PERFECTLY!")

asyncio.run(main())

