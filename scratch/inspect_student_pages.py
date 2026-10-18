import asyncio
from playwright.async_api import async_playwright

async def inspect_pages(user, pwd, label):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})

        await context.request.post("http://localhost:3000/api/auth/login", data={
            "identifier": user,
            "password": pwd,
            "remember_me": False
        })

        page = await context.new_page()

        for route in ["/", "/sessions", "/attendance", "/assignments", "/quizzes", "/exams", "/performance", "/gradebook", "/transcripts"]:
            await page.goto(f"http://localhost:3000{route}", wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            text = await page.inner_text("main")
            print(f"=== {label} on {route} ===")
            print(text[:250].replace('\n', ' -- '))

        await browser.close()

async def main():
    await inspect_pages("ibn.benin@lait.training", "ibn.benin@123456", "IBN (MANAGED)")
    await inspect_pages("anna.medzi@gmail.com", "Ann_a00--658", "ANNA (INDIVIDUAL)")

asyncio.run(main())

