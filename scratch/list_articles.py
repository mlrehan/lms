import re

files = [
    'frontend/src/content/help/corporate-manager/getting-started.ts',
    'frontend/src/content/help/corporate-manager/your-people.ts',
    'frontend/src/content/help/corporate-manager/learning-and-results.ts',
    'frontend/src/content/help/corporate-manager/communication.ts',
    'frontend/src/content/help/corporate-manager/troubleshooting.ts',
]

all_articles = []
for f in files:
    with open(f, 'r', encoding='utf-8') as fp:
        content = fp.read()
    articles = re.findall(r'id:\s*["\']([^"\']+)["\'],\s*title:\s*["\']([^"\']+)["\']', content)
    print(f'=== {f} ===')
    for a_id, a_title in articles:
        print(f'  {a_id}: {a_title}')
        all_articles.append((a_id, a_title))

print(f'\nTotal articles: {len(all_articles)}')

