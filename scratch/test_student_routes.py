import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})

        # Login as Ibn
        await context.request.post("http://localhost:3000/api/auth/login", data={
            "identifier": "ibn.benin@lait.training",
            "password": "ibn.benin@123456",
            "remember_me": False
        })

        page = await context.new_page()

        routes = [
            "/",
            "/courses",
            "/batches",
            "/sessions",
            "/attendance",
            "/assignments",
            "/quizzes",
            "/exams",
            "/performance",
            "/transcripts",
            "/gradebook",
            "/shared-with-me",
            "/announcements",
            "/discussions",
            "/messages",
            "/notifications",
            "/account",
            "/academic"
        ]

        print("Testing routes for ibn.benin@lait.training:")
        for r in routes:
            resp = await page.goto(f"http://localhost:3000{r}", wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
            h1 = await page.query_selector("h1")
            h1_text = await h1.text_content() if h1 else "No H1"
            print(f"  {r:16} -> Status: {resp.status} | H1: {h1_text.strip()} | URL: {page.url}")

        await browser.close()

asyncio.run(run())

