import os
from playwright.sync_api import sync_playwright
import base64

ARTIFACT_DIR = r"C:\Users\User\.gemini\antigravity\brain\9001942c-51b4-4275-81e3-d45cadf73704"

def verify():
    # 1. Load icon.svg
    with open(r"d:\LAIT\LMS_ANGIGRAVITY\frontend\public\icon.svg", "rb") as f:
        svg_b64 = base64.b64encode(f.read()).decode("utf-8")
        
    with sync_playwright() as p:
        browser = p.chromium.launch()
        
        # Test A: Tab rendering in Chrome Light & Dark theme
        tab_html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    background: #0b0f19;
    color: #f1f5f9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 32px;
    display: flex;
    flex-direction: column;
    gap: 24px;
    align-items: center;
  }}
  .card {{
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px;
    width: 600px;
  }}
  .label {{
    font-size: 13px;
    font-weight: 600;
    color: #94a3b8;
    margin-bottom: 12px;
  }}
  .chrome-bar-light {{
    background: #dee1e6;
    padding: 8px 8px 0 8px;
    border-radius: 8px 8px 0 0;
  }}
  .tab-light {{
    background: #ffffff;
    color: #1f1f1f;
    padding: 8px 12px;
    border-radius: 8px 8px 0 0;
    display: inline-flex;
    align-items: center;
    gap: 10px;
    font-size: 12px;
    font-weight: 500;
    width: 220px;
  }}
  .chrome-bar-dark {{
    background: #202124;
    padding: 8px 8px 0 8px;
    border-radius: 8px 8px 0 0;
  }}
  .tab-dark {{
    background: #292a2d;
    color: #e8eaed;
    padding: 8px 12px;
    border-radius: 8px 8px 0 0;
    display: inline-flex;
    align-items: center;
    gap: 10px;
    font-size: 12px;
    font-weight: 500;
    width: 220px;
  }}
  .tab-icon {{
    height: 16px;
    width: auto;
    object-fit: contain;
  }}
  .grid {{
    display: flex;
    gap: 16px;
    align-items: center;
    background: #0f172a;
    padding: 16px;
    border-radius: 8px;
    margin-top: 10px;
  }}
  .grid-item {{
    text-align: center;
    font-size: 11px;
    color: #94a3b8;
  }}
  .grid-item img {{
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 4px;
    object-fit: contain;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="label">CHROME TAB PREVIEW - LIGHT THEME (Exact Aspect Ratio 396x548)</div>
    <div class="chrome-bar-light">
      <div class="tab-light">
        <img class="tab-icon" src="data:image/svg+xml;base64,{svg_b64}" />
        <span>LMS Console</span>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="label">CHROME TAB PREVIEW - DARK THEME (Exact Aspect Ratio 396x548)</div>
    <div class="chrome-bar-dark">
      <div class="tab-dark">
        <img class="tab-icon" src="data:image/svg+xml;base64,{svg_b64}" />
        <span>LMS Console</span>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="label">MULTI-RESOLUTION ASSET SCALING SHOWCASE</div>
    <div class="grid">
      <div class="grid-item">
        <img src="data:image/svg+xml;base64,{svg_b64}" height="64" />
        <div>64px (Vector)</div>
      </div>
      <div class="grid-item">
        <img src="data:image/svg+xml;base64,{svg_b64}" height="48" />
        <div>48px Favicon</div>
      </div>
      <div class="grid-item">
        <img src="data:image/svg+xml;base64,{svg_b64}" height="32" />
        <div>32px Tab (Retina)</div>
      </div>
      <div class="grid-item">
        <img src="data:image/svg+xml;base64,{svg_b64}" height="16" />
        <div>16px Tab</div>
      </div>
    </div>
  </div>
</body>
</html>'''
        tab_page = browser.new_page(viewport={"width": 720, "height": 620})
        tab_page.set_content(tab_html)
        tab_ss = os.path.join(ARTIFACT_DIR, "24_exact_ratio_tab_preview.png")
        tab_page.screenshot(path=tab_ss)
        print(f"Saved tab preview screenshot to: {tab_ss}")
        tab_page.close()

        # Test B: Capture Login Page
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto("http://localhost:3000/login", wait_until="networkidle")
        login_ss = os.path.join(ARTIFACT_DIR, "25_exact_ratio_login.png")
        page.screenshot(path=login_ss)
        print(f"Saved login screenshot to: {login_ss}")

        # Test C: Log in and capture Sidebar
        page.fill("input[name='identifier']", "superadmin")
        page.fill("input[name='password']", "ConsoleDrive!2026")
        page.click("button[type='submit']")
        page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("text=LMS Console", timeout=10000)
        page.wait_for_timeout(1000)
        dash_ss = os.path.join(ARTIFACT_DIR, "26_exact_ratio_dashboard_sidebar.png")
        page.screenshot(path=dash_ss)
        print(f"Saved dashboard sidebar screenshot to: {dash_ss}")

        browser.close()

if __name__ == '__main__':
    verify()
