import os
import re

for guide in ["managed-student", "individual-student"]:
    path = f"frontend/src/content/help/{guide}"
    print(f"\n==================== {guide} ====================")
    for root, _, files in os.walk(path):
        for f in files:
            if not f.endswith(".ts") or f == "index.ts":
                continue
            fp = os.path.join(root, f)
            with open(fp, "r", encoding="utf-8") as file:
                content = file.read()
            articles = re.findall(r'id:\s*["\']([^"\']+)["\'],\s*title:\s*["\']([^"\']+)["\']', content)
            images = re.findall(r'src:\s*["\']([^"\']+)["\']', content)
            print(f"\nFile: {f}")
            for a_id, a_title in articles:
                print(f"  Article: {a_id} -> {a_title}")
            for img in images:
                print(f"  Image: {img}")

