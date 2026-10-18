import asyncio
from playwright.async_api import async_playwright

async def verify_guide(page, guide_slug):
    print(f"\n==========================================")
    print(f"Verifying {guide_slug}...")
    print(f"==========================================")

    # Get index page
    index_url = f"http://localhost:3000/help/{guide_slug}"
    resp = await page.goto(index_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)
    print(f"Index {index_url} -> HTTP {resp.status}")

    # Find all article links on page
    article_links = await page.query_selector_all(f"a[href*='/help/{guide_slug}/']")
    print(f"Found {len(article_links)} article links on index page.")

    hrefs = []
    for l in article_links:
        href = await l.get_attribute("href")
        if href and href not in hrefs:
            hrefs.append(href)

    print(f"Unique article hrefs ({len(hrefs)}): {hrefs}")

    failed = []
    for href in hrefs:
        url = f"http://localhost:3000{href}" if href.startswith("/") else href
        resp = await page.goto(url, wait_until="domcontentloaded")
        slug = href.split("/")[-1]

        if resp.status != 200:
            print(f"[FAIL] {slug}: HTTP {resp.status}")
            failed.append(slug)
            continue

        h1 = await page.query_selector("h1")
        h1_text = (await h1.text_content()).strip() if h1 else "No H1"

        imgs = await page.query_selector_all("main img")
        for img in imgs:
            await img.scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            natural_width = await img.evaluate("el => el.naturalWidth")
            src = await img.get_attribute("src")
            if natural_width == 0:
                await page.wait_for_timeout(500)
                natural_width = await img.evaluate("el => el.naturalWidth")

            if natural_width == 0:
                print(f"  [IMG FAIL] broken image in {slug}: {src}")
                failed.append(f"{slug}:{src}")

        print(f"[PASS] {slug} -> '{h1_text}' | {len(imgs)} img(s) OK")

    return failed

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 1000})
        page = await context.new_page()

        m_failed = await verify_guide(page, "managed-student")
        i_failed = await verify_guide(page, "individual-student")

        # Capture a screenshot of the managed student dashboard help page
        await page.goto("http://localhost:3000/help/managed-student/dashboard", wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        await page.screenshot(path="C:/Users/User/.gemini/antigravity/brain/9001942c-51b4-4275-81e3-d45cadf73704/help_managed_student_dashboard.png", full_page=True)
        print("Captured help_managed_student_dashboard.png")

        await browser.close()

        all_failed = m_failed + i_failed
        if all_failed:
            print(f"\nFAILED: {all_failed}")
            exit(1)
        else:
            print("\nALL MANAGED AND INDIVIDUAL STUDENT ARTICLES PASSED PERFECTLY!")

asyncio.run(main())

