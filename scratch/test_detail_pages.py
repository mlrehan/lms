import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})

        await context.request.post("http://localhost:3000/api/auth/login", data={
            "identifier": "ibn.benin@lait.training",
            "password": "ibn.benin@123456",
            "remember_me": False
        })

        page = await context.new_page()

        # Assignment detail
        asgn_url = "http://localhost:3000/assignments/52fd4203-dc8d-42ff-b536-1baa7c583efe"
        resp1 = await page.goto(asgn_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        print("Assignment detail status:", resp1.status)
        print("Assignment detail text:\n", (await page.inner_text("main"))[:400].replace('\n', ' -- '))

        # Quiz detail
        quiz_url = "http://localhost:3000/quizzes/4aa218f2-341b-41ff-b525-c65972fdbed1"
        resp2 = await page.goto(quiz_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        print("\nQuiz detail status:", resp2.status)
        print("Quiz detail text:\n", (await page.inner_text("main"))[:400].replace('\n', ' -- '))

        await browser.close()

asyncio.run(run())

