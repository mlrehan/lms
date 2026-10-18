import asyncio
from playwright.async_api import async_playwright

async def inspect_user(context, username, password, user_label):
    print(f"\n==========================================")
    print(f"Inspecting {user_label} ({username})...")
    print(f"==========================================")

    page = await context.new_page()

    # Direct login via API
    login_resp = await context.request.post("http://localhost:3000/api/auth/login", data={
        "identifier": username,
        "password": password,
        "remember_me": False
    })
    print(f"API Login status: {login_resp.status}")
    if login_resp.status != 200:
        print(f"API Login failed: {await login_resp.text()}")
        return

    # Navigate to dashboard
    await page.goto("http://localhost:3000/dashboard", wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("text=Loading your account", state="detached", timeout=10000)
    except:
        pass
    await page.wait_for_timeout(2000)

    print(f"Current URL: {page.url}")

    # Inspect sidebar navigation links
    sidebar_links = await page.query_selector_all("aside nav a, aside a")
    print(f"\nSidebar links count: {len(sidebar_links)}")
    links_data = []
    for link in sidebar_links:
        href = await link.get_attribute("href")
        text = await link.text_content()
        text_clean = " ".join((text or "").split())
        links_data.append((text_clean, href))
        print(f"  - {text_clean} -> {href}")

    # Get /api/v1/users/me and permissions
    user_me = await page.evaluate("""async () => {
        try {
            const res = await fetch('/api/v1/users/me');
            return await res.json();
        } catch (e) {
            return { error: String(e) };
        }
    }""")
    print(f"\nUser details from /api/v1/users/me:")
    print(f"  ID: {user_me.get('id')}")
    print(f"  Name: {user_me.get('name') or user_me.get('full_name')}")
    print(f"  Email: {user_me.get('email')}")
    print(f"  Role: {user_me.get('role')}")
    print(f"  Roles: {user_me.get('roles')}")
    print(f"  Org ID: {user_me.get('organization_id')}")

    # Check managers linked
    managers_res = await page.evaluate("""async () => {
        try {
            const res = await fetch('/api/v1/manager-links/my-managers');
            if (res.ok) return await res.json();
            const res2 = await fetch('/api/v1/manager-links');
            if (res2.ok) return await res2.json();
            return { status: res.status, text: await res.text() };
        } catch (e) {
            return { error: String(e) };
        }
    }""")
    print(f"\nManagers linked: {managers_res}")

    # Check dashboard elements
    cards = await page.query_selector_all("main h1, main h2, main h3")
    print(f"\nDashboard Headings:")
    for c in cards:
        t = await c.text_content()
        print(f"  - {t.strip()}")

    # Check enrollments / courses for this student
    courses_res = await page.evaluate("""async () => {
        try {
            const res = await fetch('/api/v1/enrollments/my');
            if (res.ok) return await res.json();
            const res2 = await fetch('/api/v1/courses');
            return { enrollments_status: res.status, courses: await res2.json() };
        } catch (e) {
            return { error: String(e) };
        }
    }""")
    print(f"\nCourses/Enrollments: {courses_res}")

    await page.close()
    await context.clear_cookies()

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})

        await inspect_user(context, "ibn.benin@lait.training", "ibn.benin@123456", "MANAGED STUDENT")
        await inspect_user(context, "anna.medzi@gmail.com", "Ann_a00--658", "INDIVIDUAL STUDENT")

        await browser.close()

asyncio.run(main())

