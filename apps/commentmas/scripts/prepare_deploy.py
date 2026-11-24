"""Stage only source analysis and public presentation data, excluding user records."""
import shutil
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root/'data/processed/BAHKmi4F1L8_20261026-144540'
destination = root/'deploy-data'
files = ['01_filter/filtered.json', '02_group/groups.json', '03_agents/agents.json',
         '04_web/catalog.json']
for name in files:
    target = destination/name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source/name, target)
grouped = json.loads((source/'02_group/groups.json').read_text(encoding='utf-8'))
comments = [c for group in grouped['groups'] for c in group['comments']]+grouped['other_opinions']['comments']
keys = {hashlib.sha256(json.dumps(['en', c['text']], sort_keys=True, ensure_ascii=False).encode()).hexdigest() for c in comments}
translations = json.loads((source/'04_web/translations.json').read_text(encoding='utf-8'))
(destination/'04_web/translations.json').write_text(json.dumps({k: v for k, v in translations.items() if k in keys}, ensure_ascii=False), encoding='utf-8')
print('Deployment analysis staged without conversation, comparison or reflection records.')
