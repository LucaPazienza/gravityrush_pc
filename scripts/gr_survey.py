import json, glob, re, sys
from collections import defaultdict
d = json.load(open('out/analysis.json'))
imps = d['imports']
if isinstance(imps, dict):
    imps = list(imps.keys())
nids = []
for x in imps:
    s = x if isinstance(x, str) else str(x.get('nid', x) if isinstance(x, dict) else x)
    nids.append(s.split('#')[0])
aero = dict(re.findall(r'STUB\(\s*"([^"]+)"\s*,\s*([^)\s]+)\s*\)', open('tools/aerolib.inl', encoding='utf-8', errors='replace').read()))
files = [f for f in glob.glob('src/*.c') + glob.glob('src/*.inc') + glob.glob('src/*.h') if not f.endswith('import_names.inc')]
src = ''.join(open(f, encoding='utf-8', errors='replace').read() for f in files)
have = set(re.findall(r'"([A-Za-z0-9_+\-]+)"', src))
names = [aero.get(n) for n in nids]
known = [n for n in names if n]
missing = sorted({n for n in known if n not in have and re.match(r'_?sce', n)})
groups = defaultdict(list)
for n in missing:
    m = re.match(r'_?sce([A-Z][a-z0-9]*)', n)
    groups[m.group(1) if m else 'altro'].append(n)
print(f'{len(nids)} import; {len(known)} con nome in aerolib; {len(missing)} funzioni sce* senza implementazione nel runtime')
print('Per libreria:', ', '.join(f'{k}={len(v)}' for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))))
print()
for k in ('Font',):
    if k in groups:
        print(f'--- {k} ({len(groups[k])}) ---'); print(' '.join(groups[k])); print()
print('--- tutte le altre, per libreria ---')
for k, v in sorted(groups.items()):
    if k != 'Font':
        print(f'[{k}]', ' '.join(v))
