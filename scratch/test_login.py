import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await context.new_page()

        await page.goto("http://localhost:3000/login", wait_until="domcontentloaded")
        await page.wait_for_selector('input[name="identifier"]')
        await page.fill('input[name="identifier"]', "anna.medzi@gmail.com")
        await page.fill('input[name="password"]', "Ann_a00--658")
        await page.click('button[type="submit"]')

        await page.wait_for_timeout(3000)

        # Check for error alert
        alert = await page.query_selector('[role="alert"]')
        if alert:
            print("Alert text:", await alert.text_content())
        else:
            print("No alert found. Current URL:", page.url)

asyncio.run(run())

