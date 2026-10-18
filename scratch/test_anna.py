import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})

        # Test direct API login
        login_res = await context.request.post("http://localhost:3000/api/auth/login", data={
            "identifier": "anna.medzi@gmail.com",
            "password": "Ann_a00--658",
            "remember_me": False
        })
        print("API login status:", login_res.status)

        page = await context.new_page()
        await page.goto("http://localhost:3000/", wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("text=Loading your account", state="detached", timeout=15000)
        except Exception as e:
            print("wait for detached exception:", e)

        await page.wait_for_timeout(2000)
        print("Final URL:", page.url)

        # Print all visible text
        body_text = await page.inner_text("body")
        print("Body text:\n", body_text[:1000])

        # Query all links
        links = await page.query_selector_all("a")
        print(f"Total links: {len(links)}")
        for l in links:
            href = await l.get_attribute("href")
            t = await l.text_content()
            print(f"  {t.strip()} -> {href}")

        await browser.close()

asyncio.run(run())

