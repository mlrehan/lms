import asyncio
from playwright.async_api import async_playwright

async def inspect_student_data(user, pwd, label):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})

        await context.request.post("http://localhost:3000/api/auth/login", data={
            "identifier": user,
            "password": pwd,
            "remember_me": False
        })

        page = await context.new_page()

        # Check /assignments
        await page.goto("http://localhost:3000/assignments", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        asgn_links = await page.query_selector_all("main a[href*='/assignments/']")
        print(f"\n[{label}] Assignments links count: {len(asgn_links)}")
        for l in asgn_links:
            print("  Assignment:", await l.get_attribute("href"), await l.text_content())

        # Check /quizzes
        await page.goto("http://localhost:3000/quizzes", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        quiz_links = await page.query_selector_all("main a[href*='/quizzes/']")
        print(f"[{label}] Quizzes links count: {len(quiz_links)}")
        for l in quiz_links:
            print("  Quiz:", await l.get_attribute("href"), await l.text_content())

        # Check /batches
        await page.goto("http://localhost:3000/batches", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        batch_links = await page.query_selector_all("main a[href*='/batches/']")
        print(f"[{label}] Batches links count: {len(batch_links)}")
        for l in batch_links:
            print("  Batch:", await l.get_attribute("href"), await l.text_content())

        # Check /performance
        await page.goto("http://localhost:3000/performance", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        options = await page.query_selector_all("main select option")
        print(f"[{label}] Performance select options: {len(options)}")
        for o in options:
            print("  Option:", await o.get_attribute("value"), await o.text_content())

        await browser.close()

async def main():
    await inspect_student_data("ibn.benin@lait.training", "ibn.benin@123456", "IBN")
    await inspect_student_data("anna.medzi@gmail.com", "Ann_a00--658", "ANNA")

asyncio.run(main())

