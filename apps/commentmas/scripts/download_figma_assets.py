"""Download the exact exported Figma assets; runtime uses local copies only."""
import concurrent.futures
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def download(item):
    name, url = item
    path = ROOT / 'frontend/public/assets' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', url, '-o', str(path)], check=True)
    return name, path.stat().st_size

if __name__ == '__main__':
    assets = json.loads((ROOT / 'scripts/figma-assets.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for result in pool.map(download, assets.items()):
            print(*result)
