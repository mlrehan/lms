import os
from PIL import Image
from playwright.sync_api import sync_playwright

def get_exact_svg(stroke_w=22, fill_color="#FF0000"):
    # EXACT aspect ratio and coordinates matching original.jpg (396 x 548)
    # Ratio: 396 / 548 = 0.7226 (Width), 548 / 396 = 1.3838 (Height)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 396 548" width="100%" height="100%">
  <!-- Top Left Mouse Button -->
  <rect x="0" y="0" width="190" height="136" rx="3" fill="{fill_color}"/>

  <!-- Top Right Mouse Button -->
  <rect x="206" y="0" width="190" height="136" rx="3" fill="{fill_color}"/>

  <!-- Lower Shield Body (Straight sides down to 394, bottom U-curve to 548) -->
  <path d="M 0 152 H 396 V 394 C 396 480 300 548 198 548 C 96 548 0 480 0 394 Z" fill="{fill_color}"/>

  <!-- White Hand Cursor Vector -->
  <g fill="none" stroke="#FFFFFF" stroke-width="{stroke_w}" stroke-linecap="round" stroke-linejoin="round">
    <!-- Extended Index Finger -->
    <path d="M 116 350 V 200 A 27.5 27.5 0 0 1 171 200 V 350"/>

    <!-- Folded Middle Finger -->
    <path d="M 171 268 A 25.5 25.5 0 0 1 222 268 V 345"/>

    <!-- Folded Ring Finger -->
    <path d="M 222 282 A 27.5 27.5 0 0 1 277 282 V 350"/>

    <!-- Folded Pinky Finger & Right Palm / Wrist -->
    <path d="
      M 277 298
      A 20 20 0 0 1 317 298
      V 420
      C 317 460 302 510 275 540
    "/>

    <!-- Thumb & Left Palm / Wrist -->
    <path d="
      M 116 256
      C 88 250 68 274 54 298
      C 46 312 48 326 62 338
      C 66 348 62 366 62 386
      V 420
      C 62 460 84 508 129 540
    "/>
  </g>
</svg>'''
    return svg

def build_production_assets():
    svg_content = get_exact_svg(stroke_w=22, fill_color="#FF0000")
    
    public_dir = r"d:\LAIT\LMS_ANGIGRAVITY\frontend\public"
    app_dir = r"d:\LAIT\LMS_ANGIGRAVITY\frontend\src\app"
    
    # 1. Save icon.svg
    with open(os.path.join(public_dir, "icon.svg"), "w", encoding="utf-8") as f:
        f.write(svg_content)
    with open(os.path.join(app_dir, "icon.svg"), "w", encoding="utf-8") as f:
        f.write(svg_content)
    print("Saved exact icon.svg (396x548)")

    # 2. Render high-res master image via Playwright (396x548)
    master_png = "master_emblem_396x548.png"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Render high-res at 2x scaling (792 x 1096) for crisp downsampling
        page = browser.new_page(viewport={"width": 792, "height": 1096})
        page.set_content(svg_content)
        page.screenshot(path=master_png, omit_background=True)
        browser.close()
    print("Rendered high-res master PNG")

    # 3. Open master PNG and generate proportional canvas images for square formats
    master = Image.open(master_png).convert("RGBA")
    
    def make_square_asset(canvas_size, padding_pct=0.04):
        # Calculate max height allowing small padding
        avail_h = int(canvas_size * (1 - 2 * padding_pct))
        avail_w = int(canvas_size * (1 - 2 * padding_pct))
        
        # Scale preserving exact 396 : 548 aspect ratio
        ratio = 396.0 / 548.0
        h = avail_h
        w = int(h * ratio)
        if w > avail_w:
            w = avail_w
            h = int(w / ratio)
            
        scaled = master.resize((w, h), Image.Resampling.LANCZOS)
        
        # Place in transparent square canvas
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        offset_x = (canvas_size - w) // 2
        offset_y = (canvas_size - h) // 2
        canvas.paste(scaled, (offset_x, offset_y), scaled)
        return canvas

    # Apple Touch Icon (180x180)
    touch_icon = make_square_asset(180, padding_pct=0.03)
    touch_icon.save(os.path.join(public_dir, "apple-touch-icon.png"))
    touch_icon.save(os.path.join(app_dir, "apple-icon.png"))
    print("Saved apple-touch-icon.png (180x180)")

    # PWA Icons (192x192, 512x512)
    icon_192 = make_square_asset(192, padding_pct=0.03)
    icon_192.save(os.path.join(public_dir, "icon-192.png"))
    icon_512 = make_square_asset(512, padding_pct=0.03)
    icon_512.save(os.path.join(public_dir, "icon-512.png"))
    print("Saved icon-192.png and icon-512.png")

    # Favicon Multi-Resolution ICO (16x16, 32x32, 48x48)
    ico_16 = make_square_asset(16, padding_pct=0.0) # 0 padding at 16px to maximize pixel density
    ico_32 = make_square_asset(32, padding_pct=0.0) # 0 padding at 32px to maximize pixel density
    ico_48 = make_square_asset(48, padding_pct=0.02)
    ico_64 = make_square_asset(64, padding_pct=0.02)
    
    ico_public = os.path.join(public_dir, "favicon.ico")
    ico_app = os.path.join(app_dir, "favicon.ico")
    
    # Save multi-frame ICO
    ico_32.save(ico_public, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)], append_images=[ico_16, ico_48, ico_64])
    ico_32.save(ico_app, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)], append_images=[ico_16, ico_48, ico_64])
    print("Saved multi-resolution favicon.ico (16, 32, 48, 64) to public and app!")

if __name__ == '__main__':
    build_production_assets()

