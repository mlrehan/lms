import os
import urllib.request
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\User\.gemini\antigravity\brain\9001942c-51b4-4275-81e3-d45cadf73704"

def verify_assets():
    print("--- 1. Testing HTTP Asset Endpoints ---")
    endpoints = [
        ("http://localhost:3000/favicon.ico", "image/x-icon"),
        ("http://localhost:3000/icon.svg", "image/svg+xml"),
        ("http://localhost:3000/apple-touch-icon.png", "image/png"),
        ("http://localhost:3000/apple-icon.png", "image/png"),
    ]
    for url, expected_type in endpoints:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            ct = res.headers.get("Content-Type", "")
            length = len(res.read())
            print(f"[{res.status}] {url} -> Content-Type: {ct}, Size: {length} bytes")
            assert res.status == 200, f"Failed for {url}"

def verify_browser():
    print("\n--- 2. Browser Verification with Playwright ---")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Step A: Visit Login Page
        page.goto("http://localhost:3000/login", wait_until="networkidle")
        
        # Verify Head Links
        title = page.title()
        print(f"Page Title: {title}")
        
        icons = page.eval_on_selector_all("link[rel*='icon']", "elements => elements.map(e => ({ rel: e.rel, href: e.href, type: e.type }))")
        print(f"Icon link tags in head: {icons}")
        
        login_ss = os.path.join(ARTIFACT_DIR, "21_login_page_with_brand_logo.png")
        page.screenshot(path=login_ss)
        print(f"Saved login screenshot to: {login_ss}")

        # Step B: Log in as Super Admin
        page.fill("input[name='identifier']", "superadmin")
        page.fill("input[name='password']", "ConsoleDrive!2026")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Step C: Visit Resources (Drive) page
        page.goto("http://localhost:3000/resources", wait_until="networkidle")
        page.wait_for_timeout(2000)
        
        dash_title = page.title()
        print(f"Dashboard/Resources Page Title: {dash_title}")
        
        dash_ss = os.path.join(ARTIFACT_DIR, "22_dashboard_sidebar_with_brand_logo.png")
        page.screenshot(path=dash_ss)
        print(f"Saved dashboard screenshot to: {dash_ss}")

        browser.close()

if __name__ == "__main__":
    verify_assets()
    verify_browser()

