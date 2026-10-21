import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ARTIFACTS_DIR = Path(r"C:\Users\User\.gemini\antigravity\brain\9001942c-51b4-4275-81e3-d45cadf73704")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

print("Starting complete browser verification on http://localhost:3000/batches...")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    page = context.new_page()

    # 1. Login as Super Admin
    print("Step 1: Navigating to login page...")
    page.goto("http://localhost:3000/login", wait_until="networkidle")
    time.sleep(1)

    if page.locator('input[name="identifier"]').count() > 0:
        print("Logging in as Super Admin...")
        superadmin_pwd = os.environ.get("SUPERADMIN_PASSWORD", "ConsoleDrive!2026")
        page.fill('input[name="identifier"]', "superadmin")
        page.fill('input[name="password"]', superadmin_pwd)
        page.click('button[type="submit"]')
        page.wait_for_timeout(3000)

    # 2. Go to /batches
    print("Step 2: Navigating to /batches...")
    page.goto("http://localhost:3000/batches", wait_until="networkidle")
    page.wait_for_timeout(2500)

    # Ensure table and calendar are loaded
    page.wait_for_selector("table tbody tr")
    page.wait_for_selector(".fc-view-harness")

    initial_rows = page.locator("table tbody tr").count()
    initial_events = page.locator(".fc-event").count()
    print(f"Initial state: {initial_rows} table rows, {initial_events} calendar events.")
    page.screenshot(path=str(ARTIFACTS_DIR / "batch_filter_01_initial.png"))

    # 3. Filter by Search text "Python"
    print("Step 3: Applying search filter: 'Python'...")
    search_input = page.locator('input[placeholder*="Search"]').first
    search_input.fill("Python")
    page.wait_for_timeout(2000)

    python_rows = page.locator("table tbody tr").count()
    python_events = page.locator(".fc-event").count()
    print(f"Search 'Python': {python_rows} table rows, {python_events} calendar events.")
    page.screenshot(path=str(ARTIFACTS_DIR / "batch_filter_02_search_python.png"))

    # 4. Filter by specific Batch Code "11429"
    print("Step 4: Applying search filter: '11429'...")
    search_input.fill("11429")
    page.wait_for_timeout(2000)

    b11429_rows = page.locator("table tbody tr").count()
    b11429_events = page.locator(".fc-event").count()
    print(f"Search '11429': {b11429_rows} table rows, {b11429_events} calendar events.")
    page.screenshot(path=str(ARTIFACTS_DIR / "batch_filter_03_search_11429.png"))

    # Clear search
    print("Clearing search input...")
    search_input.fill("")
    page.wait_for_timeout(1500)

    # 5. Filter by State: Active only
    print("Step 5: Applying State filter: 'Active only'...")
    state_btn = page.locator('button[aria-label="Filter by state"]').first
    if state_btn.count() > 0:
        state_btn.click()
        page.wait_for_timeout(500)
        active_opt = page.locator('[role="option"]:has-text("Active only")').first
        if active_opt.count() > 0:
            active_opt.click()
            page.wait_for_timeout(2000)

            active_rows = page.locator("table tbody tr").count()
            active_events = page.locator(".fc-event").count()
            print(f"State 'Active only': {active_rows} table rows, {active_events} calendar events.")
            page.screenshot(path=str(ARTIFACTS_DIR / "batch_filter_04_state_active.png"))

        # Clear State filter using the clear button
        print("Clearing State filter...")
        state_clear = page.locator('button[aria-label="Clear selection"]').first
        if state_clear.count() > 0:
            state_clear.click()
            page.wait_for_timeout(1500)

    # 6. Filter by Tutor: Younus Kazi
    print("Step 6: Applying Tutor filter: 'Younus'...")
    tutor_input = page.locator('input[placeholder="Any tutor"]').first
    if tutor_input.count() > 0:
        tutor_input.fill("Younus")
        page.wait_for_timeout(1500)
        yk_opt = page.locator('[role="option"]:has-text("Younus")').first
        if yk_opt.count() > 0:
            yk_opt.click()
            page.wait_for_timeout(2000)

            yk_rows = page.locator("table tbody tr").count()
            yk_events = page.locator(".fc-event").count()
            print(f"Tutor 'Younus Kazi': {yk_rows} table rows, {yk_events} calendar events.")
            page.screenshot(path=str(ARTIFACTS_DIR / "batch_filter_05_tutor_younus.png"))

        # Clear tutor selection using Clear button
        print("Clearing tutor filter...")
        tutor_clear = page.locator('button[aria-label="Clear selection"]').first
        if tutor_clear.count() > 0:
            tutor_clear.click()
            page.wait_for_timeout(1500)

    # 7. Test row action "Show in the calendar below"
    print("Step 7: Testing row action 'Show in the calendar below'...")
    row_action_btn = page.locator('button[aria-label="Row actions"]').first
    if row_action_btn.count() > 0:
        row_action_btn.click()
        page.wait_for_timeout(800)
        show_cal_item = page.locator('text="Show in the calendar below"').first
        if show_cal_item.count() > 0:
            show_cal_item.click()
            page.wait_for_timeout(2000)

            sel_rows = page.locator("table tbody tr").count()
            sel_events = page.locator(".fc-event").count()
            print(f"Single batch selected: {sel_rows} table rows, {sel_events} calendar events.")
            page.screenshot(path=str(ARTIFACTS_DIR / "batch_filter_06_single_batch_selected.png"))

            # Test clearing the single batch selection from calendar badge
            cal_clear_btn = page.locator('button[aria-label="Show every batch"]').first
            if cal_clear_btn.count() > 0:
                print("Clearing single batch selection...")
                cal_clear_btn.click()
                page.wait_for_timeout(1500)
                page.screenshot(path=str(ARTIFACTS_DIR / "batch_filter_07_cleared_back_to_all.png"))
                print(f"After clear: {page.locator('.fc-event').count()} calendar events.")

    print("Browser verification script completed successfully!")
    browser.close()
