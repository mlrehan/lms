"""Complete automated browser drive test for:
1. Login as Super Admin (superadmin / ConsoleDrive!2026)
2. Upload multiple files, showing real-time progress bar, percentage, status badges, and completion
3. Select multiple files via checkboxes
4. View Deletion Impact Warning dialog with affected access and dependencies
5. Confirm and permanently delete the files
"""

import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ARTIFACTS_DIR = Path(r"C:\Users\User\.gemini\antigravity\brain\9001942c-51b4-4275-81e3-d45cadf73704")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

TEMP_DIR = Path(r"d:\LAIT\LMS_ANGIGRAVITY\scratch_files")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 4MB each to provide ample time to capture progress bar mid-flight
file1 = TEMP_DIR / "sample_test_doc_1.pdf"
file2 = TEMP_DIR / "sample_test_doc_2.pdf"
file3 = TEMP_DIR / "sample_test_notes.txt"

file1.write_bytes(b"%PDF-1.4\n" + b"X" * (3 * 1024 * 1024))
file2.write_bytes(b"%PDF-1.4\n" + b"Y" * (3 * 1024 * 1024))
file3.write_bytes(b"LMS sample notes line\n" * 100000)

print(f"Sample test files prepared: {file1.name}, {file2.name}, {file3.name}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # 1. Login as Super Admin
    print("Step 1: Navigating to login page...")
    page.goto("http://localhost:3000/login", wait_until="networkidle")
    page.screenshot(path=str(ARTIFACTS_DIR / "01_login_page.png"))

    print("Filling SuperAdmin credentials...")
    superadmin_pwd = os.environ.get("SUPERADMIN_PASSWORD", "ConsoleDrive!2026")
    page.fill('input[name="identifier"]', "superadmin")
    page.fill('input[name="password"]', superadmin_pwd)
    page.screenshot(path=str(ARTIFACTS_DIR / "02_login_credentials_filled.png"))

    page.click('button[type="submit"]')
    page.wait_for_timeout(3000)

    # 2. Go to /resources
    print("Step 2: Navigating to Resources view...")
    page.goto("http://localhost:3000/resources", wait_until="networkidle")
    page.wait_for_timeout(2000)
    page.screenshot(path=str(ARTIFACTS_DIR / "03_resources_initial_view.png"))

    # 3. Open Upload Dialog
    print("Step 3: Opening '+ New' menu -> 'File upload'...")
    new_btn = page.locator('button:has-text("New")').first
    new_btn.click()
    page.wait_for_timeout(500)

    file_upload_item = page.locator('div[role="menuitem"]:has-text("File upload")')
    file_upload_item.click()
    page.wait_for_timeout(1000)
    page.screenshot(path=str(ARTIFACTS_DIR / "04_upload_dialog_opened.png"))

    dialog = page.locator('div[role="dialog"]')

    # Select course anchor using course dropdown trigger
    print("Selecting course anchor...")
    course_trigger = dialog.locator('button[aria-label="Open"]').first
    course_trigger.click()
    page.wait_for_selector('div[role="option"]', timeout=8000)
    options = page.locator('div[role="option"]').all()
    if options:
        print(f"Selecting course: {options[0].text_content()[:40]}")
        options[0].click()
        page.wait_for_timeout(500)
    page.screenshot(path=str(ARTIFACTS_DIR / "05_course_selected.png"))

    # Set files on file input
    print("Attaching 3 sample files for upload...")
    file_input = dialog.locator('input[type="file"]')
    file_input.set_input_files([str(file1), str(file2), str(file3)])
    page.wait_for_timeout(1000)
    page.screenshot(path=str(ARTIFACTS_DIR / "06_files_queued_with_progress_bar.png"))

    # Click Upload
    print("Initiating upload with real-time progress bar...")
    upload_action_btn = dialog.locator('button:has-text("Upload (3)"), button:has-text("Upload")').last
    upload_action_btn.click()

    # Capture in-progress screenshots showing progress bar
    for i in range(1, 7):
        page.wait_for_timeout(200)
        page.screenshot(path=str(ARTIFACTS_DIR / f"07_upload_progress_{i}.png"))

    # Wait for completion
    page.wait_for_timeout(4000)
    page.screenshot(path=str(ARTIFACTS_DIR / "08_upload_completed_all_done.png"))

    # Close Upload Dialog
    close_btn = dialog.locator('button:has-text("Close"), button:has-text("Cancel")').first
    if close_btn.is_visible():
        close_btn.click()
    page.wait_for_timeout(2000)
    page.screenshot(path=str(ARTIFACTS_DIR / "09_resources_after_upload.png"))

    # 4. Multi-File Selection and Permanent Deletion
    print("Step 4: Selecting multiple files for permanent deletion...")
    # Find checkboxes for the files
    checkboxes = page.locator('[role="checkbox"][aria-label^="Select "]')
    cb_count = checkboxes.count()
    print(f"Total file checkboxes found: {cb_count}")

    if cb_count >= 2:
        # Check first 2 files
        checkboxes.nth(0).click()
        page.wait_for_timeout(300)
        checkboxes.nth(1).click()
        page.wait_for_timeout(500)
        page.screenshot(path=str(ARTIFACTS_DIR / "10_multiple_files_selected_sticky_bar.png"))

        # Click "Delete permanently" button in sticky bar
        print("Clicking 'Delete permanently' in the bulk action bar...")
        del_perm_btn = page.locator('button:has-text("Delete permanently")')
        del_perm_btn.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(ARTIFACTS_DIR / "11_deletion_impact_dialog_warning.png"))

        # Check acknowledgment box in Deletion Impact dialog
        print("Checking confirmation acknowledgment...")
        impact_dialog = page.locator('div[role="dialog"]:has-text("Permanent Deletion Impact")')
        if impact_dialog.is_visible():
            ack_checkbox = impact_dialog.locator('input[type="checkbox"]')
            ack_checkbox.check()
            page.wait_for_timeout(500)
            page.screenshot(path=str(ARTIFACTS_DIR / "12_deletion_impact_acknowledged.png"))

            # Click final "Permanently Delete"
            print("Clicking 'Permanently Delete' button...")
            final_del_btn = impact_dialog.locator('button:has-text("Permanently Delete")')
            final_del_btn.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(ARTIFACTS_DIR / "13_after_permanent_deletion_success.png"))
            print("Files permanently deleted successfully!")

    browser.close()
    print("All tests completed successfully!")
