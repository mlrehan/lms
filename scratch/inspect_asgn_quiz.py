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

        # Assignments
        await page.goto("http://localhost:3000/assignments", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        items = await page.query_selector_all("main tbody tr, main [role='row'], main li, main button")
        print(f"Assignments elements: {len(items)}")

        # Check HTML of assignments
        main_html = await page.inner_html("main")
        print("Assignments HTML length:", len(main_html))
        # Look for buttons or links inside main
        buttons = await page.query_selector_all("main button, main a")
        for b in buttons:
            txt = await b.text_content()
            href = await b.get_attribute("href")
            print("  Btn/Link:", txt.strip(), "->", href)

        # Quizzes
        await page.goto("http://localhost:3000/quizzes", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        q_buttons = await page.query_selector_all("main button, main a")
        print(f"Quizzes btns/links: {len(q_buttons)}")
        for b in q_buttons:
            txt = await b.text_content()
            href = await b.get_attribute("href")
            print("  Quiz Btn/Link:", txt.strip(), "->", href)

        await browser.close()

asyncio.run(run())

