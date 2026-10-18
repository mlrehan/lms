import os
from playwright.sync_api import sync_playwright
from PIL import Image

def get_enterprise_svg():
    # Perfected Enterprise Vector SVG for LAIT LMS Console
    # Grid: 512x512
    # Bounding Box:
    # Outer width: 432px (X: 40 to 472, Center: 256)
    # Outer height: 456px (Y: 28 to 484, Center: 256)
    #
    # Top buttons:
    # Left: X=40..246, Y=28..138 (w=206, h=110)
    # Right: X=266..472, Y=28..138 (w=206, h=110)
    # Horizontal gap: Y=138..158 (20px)
    # Vertical gap: X=246..266 (20px)
    #
    # Lower Shield:
    # Top edge: Y=158, X=40..472 (w=432)
    # Sides: straight down to Y=326
    # Bottom curve: smooth U-shield down to Y=484, Center X=256
    #
    # Hand Cursor:
    # White stroke width: 22px
    # Stroke caps & joins: round
    # Index finger: Left X=168, Right X=228 (Width=60, Center=198). Tip Y=202 (cap r=30).
    # Middle finger: Left X=228, Right X=286 (Width=58, Center=257). Tip Y=270 (cap r=29).
    # Ring finger: Left X=286, Right X=342 (Width=56, Center=314). Tip Y=286 (cap r=28).
    # Pinky finger: Left X=342, Right X=388 (Width=46, Center=365). Tip Y=302 (cap r=23).
    # Outer palm & wrist: Curves down from pinky (388, 302) -> (388, 370) -> (376, 420) -> (356, 456) -> (336, 474).
    # Thumb & left palm: Curves from index (168, 306) -> (114, 272) -> tip (92, 298) -> (104, 346) -> (104, 400) -> (116, 444) -> (146, 466) -> (176, 474).
    # Wrist terminates smoothly along the shield's curved base.

    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <defs>
    <!-- Enterprise Red Gradient: Vibrant, authoritative, optimal contrast on both dark & light browser chrome -->
    <linearGradient id="laitBrandRed" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FF1A24"/>
      <stop offset="100%" stop-color="#D90412"/>
    </linearGradient>
  </defs>

  <!-- Left Mouse Button -->
  <path d="M 48 28 H 242 A 4 4 0 0 1 246 32 V 134 A 4 4 0 0 1 242 138 H 44 A 4 4 0 0 1 40 134 V 36 A 8 8 0 0 1 48 28 Z" fill="url(#laitBrandRed)"/>

  <!-- Right Mouse Button -->
  <path d="M 270 28 H 464 A 8 8 0 0 1 472 36 V 134 A 4 4 0 0 1 468 138 H 270 A 4 4 0 0 1 266 134 V 32 A 4 4 0 0 1 270 28 Z" fill="url(#laitBrandRed)"/>

  <!-- Lower Mouse Shield Body -->
  <path d="M 40 158 H 472 V 326 C 472 422 374 484 256 484 C 138 484 40 422 40 326 Z" fill="url(#laitBrandRed)"/>

  <!-- Stylized Pointer Hand Cursor -->
  <g fill="none" stroke="#FFFFFF" stroke-width="22" stroke-linecap="round" stroke-linejoin="round">
    <!-- Extended Index Finger -->
    <path d="M 168 344 V 202 A 30 30 0 0 1 228 202 V 344"/>

    <!-- Folded Middle Finger -->
    <path d="M 228 270 A 29 29 0 0 1 286 270 V 340"/>

    <!-- Folded Ring Finger -->
    <path d="M 286 286 A 28 28 0 0 1 342 286 V 344"/>

    <!-- Folded Pinky Finger & Right Palm / Wrist -->
    <path d="
      M 342 302
      A 23 23 0 0 1 388 302
      V 370
      C 388 410 376 440 358 458
      L 336 474
    "/>

    <!-- Thumb & Left Palm / Wrist -->
    <path d="
      M 168 306
      C 146 290 126 270 112 272
      C 96 274 90 288 92 304
      C 94 324 104 336 104 358
      C 104 382 100 406 102 426
      C 104 450 118 466 142 472
      L 176 474
    "/>
  </g>
</svg>'''
    return svg

def build_all_assets():
    svg_content = get_enterprise_svg()
    
    # Target directories
    public_dir = r'd:\LAIT\LMS_ANGIGRAVITY\frontend\public'
    app_dir = r'd:\LAIT\LMS_ANGIGRAVITY\frontend\src\app'
    os.makedirs(public_dir, exist_ok=True)
    os.makedirs(app_dir, exist_ok=True)
    
    # Save SVG to public and app
    with open(os.path.join(public_dir, 'icon.svg'), 'w', encoding='utf-8') as f:
        f.write(svg_content)
    with open(os.path.join(app_dir, 'icon.svg'), 'w', encoding='utf-8') as f:
        f.write(svg_content)
    print('Saved icon.svg')
    
    # Render PNGs using Playwright
    temp_pngs = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for size in [16, 32, 48, 64, 180, 192, 512]:
            page = browser.new_page(viewport={'width': size, 'height': size})
            page.set_content(svg_content)
            path = f'temp_icon_{size}.png'
            page.screenshot(path=path, omit_background=True)
            temp_pngs[size] = path
            page.close()
        browser.close()
        
    # Copy / Save specific assets
    # Apple Touch Icon (180x180)
    img_180 = Image.open(temp_pngs[180])
    img_180.save(os.path.join(public_dir, 'apple-touch-icon.png'))
    img_180.save(os.path.join(app_dir, 'apple-icon.png'))
    print('Saved apple-touch-icon.png (180x180)')
    
    # PWA icons
    img_192 = Image.open(temp_pngs[192])
    img_192.save(os.path.join(public_dir, 'icon-192.png'))
    img_512 = Image.open(temp_pngs[512])
    img_512.save(os.path.join(public_dir, 'icon-512.png'))
    print('Saved icon-192.png and icon-512.png')
    
    # Multi-resolution ICO (16x16, 32x32, 48x48)
    img_16 = Image.open(temp_pngs[16])
    img_32 = Image.open(temp_pngs[32])
    img_48 = Image.open(temp_pngs[48])
    
    ico_public = os.path.join(public_dir, 'favicon.ico')
    ico_app = os.path.join(app_dir, 'favicon.ico')
    
    # Save as true Windows/Browser multi-size ICO
    img_32.save(ico_public, format='ICO', sizes=[(16, 16), (32, 32), (48, 48)], append_images=[img_16, img_48])
    img_32.save(ico_app, format='ICO', sizes=[(16, 16), (32, 32), (48, 48)], append_images=[img_16, img_48])
    print('Saved multi-resolution favicon.ico to public and app!')

if __name__ == '__main__':
    build_all_assets()

