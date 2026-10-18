import asyncio
import os
import re
from playwright.async_api import async_playwright

REDACTION_CSS = """
.privacy-blurred {
    filter: blur(6px) !important;
    user-select: none !important;
}
"""

REDACTION_SCRIPT = """
(sensitivePatterns) => {
    // Add blur style
    if (!document.getElementById('privacy-blur-style')) {
        const style = document.createElement('style');
        style.id = 'privacy-blur-style';
        style.innerHTML = `.privacy-blurred { filter: blur(6px) !important; user-select: none !important; }`;
        document.head.appendChild(style);
    }

    const compiled = sensitivePatterns.map(p => new RegExp(p, 'i'));

    function redactNode(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            const val = node.nodeValue;
            for (const rx of compiled) {
                if (rx.test(val)) {
                    const span = document.createElement('span');
                    span.className = 'privacy-blurred';
                    span.textContent = val;
                    if (node.parentNode) {
                        node.parentNode.replaceChild(span, node);
                    }
                    break;
                }
            }
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.tagName !== 'SCRIPT' && node.tagName !== 'STYLE' && !node.classList.contains('privacy-blurred')) {
                for (const child of Array.from(node.childNodes)) {
                    redactNode(child);
                }
            }
        }
    }

    redactNode(document.body);
}
"""

async def capture_user(context, username, password, out_dir, sensitive_patterns):
    print(f"\n==========================================")
    print(f"Logging in as {username} for {out_dir}...")
    print(f"==========================================")

    login_res = await context.request.post("http://localhost:3000/api/auth/login", data={
        "identifier": username,
        "password": password,
        "remember_me": False
    })
    if login_res.status != 200:
        print(f"Login failed: {await login_res.text()}")
        return

    page = await context.new_page()

    # Define targets: (filename, url, wait_selector, pre_action)
    targets = [
        ("dashboard.webp", "http://localhost:3000/", "main", "dashboard"),
        ("account.webp", "http://localhost:3000/account", "main", None),
        ("courses.webp", "http://localhost:3000/courses", "main", None),
        ("batches.webp", "http://localhost:3000/batches", "main", None),
        ("timetable.webp", "http://localhost:3000/sessions", "main", None),
        ("attendance.webp", "http://localhost:3000/attendance", "main", None),
        ("assignments.webp", "http://localhost:3000/assignments", "main", None),
        ("assignment-detail.webp", "http://localhost:3000/assignments/52fd4203-dc8d-42ff-b536-1baa7c583efe", "main", None),
        ("quizzes.webp", "http://localhost:3000/quizzes", "main", None),
        ("quiz-detail.webp", "http://localhost:3000/quizzes/4aa218f2-341b-41ff-b525-c65972fdbed1", "main", None),
        ("examinations.webp", "http://localhost:3000/exams", "main", None),
        ("performance-batch.webp", "http://localhost:3000/performance", "main", "performance"),
        ("messages.webp", "http://localhost:3000/messages", "main", None),
        ("notifications.webp", "http://localhost:3000/notifications", "main", None),
        ("announcements.webp", "http://localhost:3000/announcements", "main", None),
        ("discussions.webp", "http://localhost:3000/discussions", "main", None),
        ("shared-with-me.webp", "http://localhost:3000/shared-with-me", "main", None),
    ]

    os.makedirs(out_dir, exist_ok=True)

    for filename, url, selector, pre_action in targets:
        print(f"Capturing {filename} from {url}...")
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_selector(selector, timeout=10000)

            # Wait for any Loading banner to detach
            try:
                await page.wait_for_selector("text=Loading", state="detached", timeout=6000)
            except:
                pass

            if pre_action == "performance":
                # Select batch 11429 if present
                select_elem = await page.query_selector("main select")
                if select_elem:
                    options = await page.query_selector_all("main select option")
                    for opt in options:
                        val = await opt.get_attribute("value")
                        if val and val != "":
                            await select_elem.select_option(val)
                            break
                    await page.wait_for_timeout(2000)

            await page.wait_for_timeout(1000)

            # Apply privacy redactions
            await page.evaluate(REDACTION_SCRIPT, sensitive_patterns)
            await page.wait_for_timeout(500)

            out_path = os.path.join(out_dir, filename)
            # Save screenshot
            await page.screenshot(path=out_path, type="webp", quality=95)
            print(f"  -> Saved {out_path} ({os.path.getsize(out_path)} bytes)")

        except Exception as e:
            print(f"  [ERROR] Failed capturing {filename}: {e}")

    await page.close()
    await context.clear_cookies()

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})

        # 1. Managed student (Ibn Benin)
        await capture_user(
            context,
            "ibn.benin@lait.training",
            "ibn.benin@123456",
            "frontend/public/help/managed-student",
            [
                "ibn\\.benin@lait\\.training",
                "Ibn Benin",
                "Ibn",
                "Benin",
                "Lakshmi Mathiyazhagan",
                "lakshmimathiyazhagan4@gmail\\.com",
                "Wise",
                "WISE"
            ]
        )

        # 2. Individual student (Anna Medzi)
        await capture_user(
            context,
            "anna.medzi@gmail.com",
            "Ann_a00--658",
            "frontend/public/help/individual-student",
            [
                "anna\\.medzi@gmail\\.com",
                "Anna Rózsa Medzihradszky",
                "Anna Rózsa",
                "Medzihradszky",
                "Anna"
            ]
        )

        await browser.close()
        print("\nAll student screenshots captured successfully!")

asyncio.run(main())

