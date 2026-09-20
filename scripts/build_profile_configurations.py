"""Rebuild the release BPM resource from verified parser-v5 TJA mappings.

Run explicitly with --model-root, --ese-root and --version. No player data is used.
The external model checkout supplies taiko_model; the plugin has no runtime
dependency on it. Any missing mapping, note mismatch or fingerprint mismatch
aborts before publishing resources.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import rating
from profile_data import BANDS, bpm_band
from storage import load_charts


def build(model_root, ese_root, version, output):
    sys.path.insert(0, str(model_root))
    from taiko_model.parsers import get_parser
    from taiko_model import taiko_patterns

    source = ROOT / 'resource/charts.v1.json.gz'
    charts = load_charts(source)
    mapping_path = model_root / 'ml/artifacts/parser-v5/mapping-report.v1.json'
    mapping = json.loads(mapping_path.read_text('utf-8'))
    expected = {key for key, chart in charts.items() if chart.get('feature')}
    _, parse = get_parser('v5')
    previous_band = taiko_patterns._bpm_band
    taiko_patterns._bpm_band = bpm_band
    cache, rebuilt, provenance = {}, {}, []
    try:
        for row in mapping['mappings']:
            key = (row['songNo'], row['level'])
            if key not in expected:
                continue
            selected = row.get('selected') or {}
            relative = selected['relativePath']
            path = (ese_root / relative).resolve()
            if not path.is_relative_to(ese_root.resolve()):
                raise ValueError(f'TJA mapping escapes source root: {key}')
            if relative not in cache:
                cache[relative] = parse(path, ese_root)
            course = next(c for c in cache[relative] if c.course == selected['course'])
            if course.fingerprint != selected['fingerprint'] or course.total_notes != charts[key]['totalNotes']:
                raise ValueError(f'TJA fingerprint or note count mismatch: {key}')
            if key in rebuilt:
                raise ValueError(f'Duplicate mapping: {key}')
            chart = copy.deepcopy(charts[key])
            chart['feature']['rhythmProfile'] = course.rhythm_profile
            rebuilt[key] = chart
            provenance.append({'id':key[0], 'level':key[1], 'path':relative,
                               'fingerprint':course.fingerprint, 'totalNotes':course.total_notes})
            if len(rebuilt) % 200 == 0:
                print(f'Verified {len(rebuilt)} / {len(expected)}', flush=True)
    finally:
        taiko_patterns._bpm_band = previous_band
    if set(rebuilt) != expected:
        raise ValueError(f'Missing mapped charts: {sorted(expected - set(rebuilt))}')

    perfect = []
    for (song, level), chart in rebuilt.items():
        score = {'id':song, 'level':level, 'title':chart['title'],
                 'goodCount':chart['totalNotes'], 'okCount':0, 'ngCount':0, 'dondafulComboCount':1}
        perfect.append({**score, **rating.calculate_ai_values(chart, score), 'chart':chart, 'feature':chart['feature']})
    full = {cell['key']:cell for cell in rating.calculate_rhythm_ability(perfect, rebuilt)['cells']}
    _, prevalence = rating._rhythm_catalog_prevalence(rebuilt)
    cells = []
    for key, count in sorted(prevalence.items()):
        pattern, band = key.split('|')
        cells.append({'key':key, 'pattern':pattern, 'band':band,
                      'ceiling':full.get(key, {}).get('score'), 'catalogSamples':count})
    resource = {'schemaVersion':1, 'version':version,
                'chartsSha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'bands':BANDS,
                'profiles':[{'id':key[0], 'level':key[1], 'totalNotes':chart['totalNotes'],
                             'rhythmProfile':{field:chart['feature']['rhythmProfile'].get(field, [])
                                              for field in ('cells', 'arrangementCells')}}
                            for key, chart in sorted(rebuilt.items())], 'cells':cells}
    compressed = gzip.compress(json.dumps(resource, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), compresslevel=9, mtime=0)
    manifest = {'schemaVersion':1, 'version':version, 'chartsSha256':resource['chartsSha256'],
                'profiles':len(rebuilt), 'configurations':len(cells), 'bands':BANDS,
                'sha256':hashlib.sha256(compressed).hexdigest(), 'compressedBytes':len(compressed),
                'source':'ESE TJA with parser-v5 mapping; fingerprint and totalNotes verified',
                'baseline':'Full-good catalog with unchanged rating.py configuration aggregation',
                'mappingSha256':hashlib.sha256(mapping_path.read_bytes()).hexdigest()}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'profile_configurations.v1.json.gz').write_bytes(compressed)
    (output / 'profile_configurations.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf-8')
    proof = gzip.compress(json.dumps(provenance, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), mtime=0)
    (output / 'profile_configurations.provenance.json.gz').write_bytes(proof)
    print(json.dumps({'profiles':len(rebuilt), 'configurations':len(cells), 'sha256':manifest['sha256']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-root', required=True, type=Path)
    parser.add_argument('--ese-root', required=True, type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'resource')
    args = parser.parse_args()
    build(args.model_root.resolve(), args.ese_root.resolve(), args.version, args.output.resolve())
