import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})

        await context.request.post("http://localhost:3000/api/auth/login", data={
            "identifier": "ibn.benin@lait.training",
            "password": "ibn.benin@123456",
            "remember_me": False
        })

        page = await context.new_page()

        # Dashboard
        await page.goto("http://localhost:3000/", wait_until="domcontentloaded")
        await page.wait_for_selector("text=Loading your dashboard", state="detached", timeout=15000)
        await page.wait_for_timeout(1000)
        print("=== Dashboard Loaded ===")
        print(await page.inner_text("main"))

        # Batches
        await page.goto("http://localhost:3000/batches", wait_until="domcontentloaded")
        await page.wait_for_selector("text=Loading", state="detached", timeout=15000)
        await page.wait_for_timeout(1000)
        print("=== Batches Loaded ===")
        print((await page.inner_text("main"))[:400])

        # Sessions
        await page.goto("http://localhost:3000/sessions", wait_until="domcontentloaded")
        await page.wait_for_selector("text=Loading", state="detached", timeout=15000)
        await page.wait_for_timeout(1000)
        print("=== Sessions Loaded ===")
        print((await page.inner_text("main"))[:400])

        # Performance
        await page.goto("http://localhost:3000/performance", wait_until="domcontentloaded")
        await page.wait_for_selector("select", timeout=10000)
        options = await page.query_selector_all("select option")
        print("=== Performance Options ===")
        for o in options:
            print("  ", await o.get_attribute("value"), await o.text_content())

        await browser.close()

asyncio.run(inspect())

