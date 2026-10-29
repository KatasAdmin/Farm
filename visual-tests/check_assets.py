"""Check every supplied image through the local, real FastAPI static mount."""
import json
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = 'http://127.0.0.1:8085'


def main():
    paths = sorted('/' + p.relative_to(ROOT).as_posix()
                   for p in (ROOT / 'assets').rglob('*') if p.suffix in {'.png', '.webp'})
    assert len(paths) >= 158, f'Original asset pack is incomplete: {len(paths)}'
    for name in ('coop', 'market', 'shop', 'wallet', 'profile'):
        assert '/assets/redesign/' + name + '.webp' in paths
    with httpx.Client(base_url=BASE_URL) as client:
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers['content-type'].startswith('image/'), path
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = browser.new_page()
        page.goto(BASE_URL)
        decoded = page.evaluate('''async paths => Promise.all(paths.map(path => new Promise(resolve => {
            const image = new Image();
            image.onload = () => resolve({path, width:image.naturalWidth, height:image.naturalHeight});
            image.onerror = () => resolve({path, width:0, height:0}); image.src = path;
        })))''', paths)
        assert all(row['width'] > 0 and row['height'] > 0 for row in decoded), decoded
        browser.close()
    print(json.dumps({'images': len(paths), 'http': '200 image/*', 'decoded': len(decoded), 'result': 'PASS'}))


if __name__ == '__main__':
    main()
