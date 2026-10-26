"""Data contracts for Profile, seven BPM bands and versioned configuration history."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__:
    from .rating import calculate_rhythm_ability, chart_for_record
else:
    from rating import calculate_rhythm_ability, chart_for_record

BANDS=[('ultraslow','超慢速','0–<110'),('slow','慢速','110–<140'),
       ('normal','常规','140–<180'),('fast','高速','180–<220'),
       ('ultrafast','超高速','220–<280'),('rapid','急速','280–330'),('laser','激光级','>330')]
RESOURCE=Path(__file__).resolve().parent/'resource'/'profile_configurations.v1.json.gz'
CONFIGURATION_ALGORITHM = 'rhythm-v2-r1-bpm7-branches-v1'

def bpm_band(value):
    value=abs(float(value))
    for upper,key in ((110,'ultraslow'),(140,'slow'),(180,'normal'),(220,'fast'),(280,'ultrafast')):
        if value<upper:return key
    return 'rapid' if value<=330 else 'laser'

def load_configuration_catalog(charts,path=None):
    path=Path(path or RESOURCE)
    try:
        raw=path.read_bytes();payload=json.loads(gzip.decompress(raw))
        if payload['schemaVersion']!=1 or payload['bands']!=[list(b) for b in BANDS]:
            raise ValueError('不支持的 BPM 分档版本')
        source=RESOURCE.parent/'charts.v1.json.gz'
        if payload['chartsSha256']!=hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError('配置资源与谱面库版本不匹配')
        rebuilt={}
        for item in payload['profiles']:
            key=(item['id'],item['level']);chart=charts.get(key)
            if not chart or chart.get('totalNotes')!=item['totalNotes']:
                raise ValueError('配置资源与谱面集合不匹配')
            rebuilt[key]={**chart,'feature':{**(chart.get('feature') or {}),'rhythmProfile':item['rhythmProfile']}}
        return {'available':True,'version':payload['version'],'hash':hashlib.sha256(raw).hexdigest(),
                'chartsHash':payload['chartsSha256'],'catalog':rebuilt,'cells':payload['cells'],'bands':BANDS}
    except (OSError,ValueError,KeyError,TypeError) as error:
        return {'available':False,'version':None,'catalog':{},'cells':[],'bands':BANDS,'error':str(error)}

def configuration_scores(records,catalog):
    if not catalog['available']:
        return {'available':False,'version':None,'bands':BANDS,'cells':[],'error':catalog.get('error','配置数据不可用')}
    selected=[]
    for row in records:
        chart=catalog['catalog'].get((row['id'],row['level']))
        if chart:
            chart=chart_for_record(chart,row)
            if chart.get('branchProfile'):
                chart={**chart,'feature':{**chart['feature'],'rhythmProfile':chart['configurationRhythmProfile']}}
            selected.append({**row,'chart':chart,'feature':chart['feature']})
    current={c['key']:c for c in calculate_rhythm_ability(selected,catalog['catalog'])['cells']}
    cells=[]
    for item in catalog['cells']:
        value=current.get(item['key'])
        cells.append({**item,'score':value['score'] if value else None,
                      'playerSamples':value['charts'] if value else 0,
                      'reason':None if value else 'catalog_insufficient' if item['catalogSamples'] < 3 else 'player_insufficient'})
    return {'available':True,'version':catalog['version'],'resourceHash':catalog['hash'],
            'algorithmVersion':CONFIGURATION_ALGORITHM,'chartsHash':catalog['chartsHash'],'bands':BANDS,'cells':cells}


def configuration_history_payload(analysis):
    """Keep scoring inputs, not credentials, API envelopes or mutable sync timestamps."""
    fields = ('id','level','goodCount','okCount','ngCount','dondafulComboCount',
              'aiConstantRaw','aiConstant','rating','accuracy','branchProfile','branchPaths','totalNotes')
    inputs = [{k:r.get(k) for k in fields} for r in analysis['records']]
    inputs.sort(key=lambda r:(r['id'],r['level']))
    config = analysis['profileConfigurations']
    return {'schemaVersion':1,'algorithmVersion':config['algorithmVersion'],
            'meta':analysis['meta'],'source':analysis['profileSource'],
            'configurations':config,'inputs':inputs}


def archive_configuration_resources(directory, config):
    """One immutable copy of shared weights per hash, independent of player count."""
    directory = Path(directory) / 'catalog_versions'
    directory.mkdir(parents=True, exist_ok=True)
    for name, digest in (('charts.v1.json.gz', config['chartsHash']),
                         (RESOURCE.name, config['resourceHash'])):
        target = directory / (digest + '.json.gz')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError('归档谱面资源校验失败')
            continue
        raw = (RESOURCE.parent / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('谱面资源在同步期间发生变化')
        # Atomic publication; concurrent players publish identical content.
        import os, tempfile
        fd, temporary = tempfile.mkstemp(dir=directory, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)

def unique_score_rows(rows):
    """One chart per (song, difficulty), retaining exclusive historical best badges."""
    selected={}
    for original in rows:
        if original.get('level') not in (4,5):continue
        key=(original.get('id'),original['level']);old=selected.get(key)
        row=dict(original)
        if old:
            winner=row if float(row.get('highScore') or 0)>float(old.get('highScore') or 0) else old
            row=dict(winner)
            for field in ('clearCount','fullComboCount','dondafulComboCount','bestScoreRank'):
                row[field]=max(original.get(field) or 0,old.get(field) or 0)
        selected[key]=row
    return list(selected.values())


def score_sync_changes(previous, current):
    """Compare current bests with the preceding sync, never a historical peak."""
    old = {(row["song_no"], row["level"]): row for row in previous}
    items = []
    if old:
        for row in unique_score_rows(current):
            before = old.get((row["id"], row["level"]))
            score = row.get("highScore")
            if score is None:
                continue
            previous_score = before.get("high_score") if before else None
            if before and previous_score is None:
                continue
            delta = int(score) - int(previous_score) if before else None
            if delta == 0:
                continue
            items.append(
                {
                    "id": row["id"],
                    "level": row["level"],
                    "title": row.get("title"),
                    "previousScore": int(previous_score) if before else None,
                    "highScore": int(score),
                    "delta": delta,
                }
            )
    items.sort(
        key=lambda row: (
            row["delta"] is None,
            -abs(row["delta"] or 0),
            row["id"],
            row["level"],
        )
    )
    return {"baseline": bool(old), "items": items}



def add_profile_value_changes(changes, previous, current, previous_scores=None):
    """Merge displayed Rating/constant changes without conflating them with game scores."""
    changes = copy.deepcopy(changes)
    compatible = (
        bool(previous)
        and changes["baseline"]
        and all(
            str((previous.get("meta") or {}).get(key) or "")
            == str(current["meta"].get(key) or "")
            for key in ("playerId", "server")
        )
        and previous.get("profileSource") == current["profileSource"]
    )
    changes["valuesBaseline"] = bool(compatible)
    if not compatible:
        return changes
    old = {(r["id"], r["level"]): r for r in previous.get("records", [])}
    old_scores = {
        (r["id"], r["level"]): r.get("highScore")
        for r in previous.get("profileScoreRows", [])
    }
    if previous_scores is not None:
        old_scores = {
            (r["song_no"], r["level"]): r.get("high_score") for r in previous_scores
        }
    scores = {
        (r["id"], r["level"]): r.get("highScore") for r in current["profileScoreRows"]
    }
    items = {(r["id"], r["level"]): r for r in changes["items"]}
    for row in current["records"]:
        key = (row["id"], row["level"])
        before = old.get(key)
        if before is None:
            continue
        values = {}
        for field, prefix, digits in (
            ("rating", "rating", 2),
            ("aiConstant", "constant", 1),
        ):
            a, b = before.get(field), row.get(field)
            if a is None or b is None:
                continue
            try:
                a, b = float(a), float(b)
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(a) and math.isfinite(b)):
                continue
            delta = round(round(b, digits) - round(a, digits), digits)
            if delta:
                values.update(
                    {
                        prefix + "Delta": delta,
                        "previous" + prefix.capitalize(): a,
                        field: b,
                    }
                )
        if not values:
            continue
        if key not in items:
            items[key] = {
                "id": row["id"],
                "level": row["level"],
                "title": row.get("title"),
                "previousScore": old_scores.get(key, before.get("highScore")),
                "highScore": scores.get(key),
                "delta": 0,
            }
        items[key].update(values)
    changes["items"] = sorted(
        items.values(),
        key=lambda r: (
            r["delta"] is None,
            -abs(r.get("constantDelta") or 0),
            -abs(r.get("ratingDelta") or 0),
            -abs(r["delta"] or 0),
            r["id"],
            r["level"],
        ),
    )
    return changes


def profile_value_baseline(analysis):
    """Small per-source baseline survives cache invalidation and model/resource updates."""
    fields = ("id", "level", "title", "rating", "aiConstant", "highScore")
    return {
        "meta": {key: analysis["meta"].get(key) for key in ("playerId", "server")},
        "profileSource": analysis["profileSource"],
        "profileScoreRows": analysis["profileScoreRows"],
        "records": [{key: r.get(key) for key in fields} for r in analysis["records"]],
    }


def build_profile_data(analysis,generated_at=None):
    generated_at=generated_at or datetime.now(timezone.utc)
    analysis=copy.deepcopy(analysis)
    records=[]
    for row in analysis.get('records') or []:
        if row.get('level') not in (4,5):continue
        value=float(row.get('rating') or 0)
        if not math.isfinite(value):continue
        row['rating']=value
        constant = row.get('aiConstant') or row.get('constant')
        row['aiConstant']=float(constant) if constant is not None and math.isfinite(float(constant)) else None
        accuracy = float(row.get('accuracy') or 0)
        row['accuracy']=accuracy if math.isfinite(accuracy) else 0
        records.append(row)
    analysis['records']=unique_score_rows(records)
    analysis.setdefault('meta',{})
    meta=analysis['meta'];meta.setdefault('playerId','未提供编号')
    analysis.setdefault('summary',{}).setdefault('rating',0)
    if analysis.get('profileRating') is not None:
        analysis['summary']['rating'] = analysis['profileRating']
    families=(analysis.get('featureAbility') or {}).get('families') or []
    ranked=sorted((r for r in families if (r.get('charts') or 0)>=3),key=lambda r:r['score'],reverse=True)
    empty={'key':'chartPower','score':0,'charts':0}
    when=analysis.get('profileSyncedAt')
    if when:
        try:label='已同步 '+datetime.fromisoformat(when).astimezone(timezone(timedelta(hours=8))).strftime('%Y.%m.%d %H:%M')
        except (ValueError,TypeError):label='同步时间未知'
    else:label='生成 '+generated_at.astimezone(timezone(timedelta(hours=8))).strftime('%Y.%m.%d %H:%M')
    configuration=analysis.get('profileConfigurations') or {'available':False,'bands':BANDS,'cells':[]}
    improvement=analysis.get('profileImprovement') or {'items':[],'targetName':'','targetRank':8}
    return {'analysis':analysis,'playerId':str(meta['playerId']),
            'serverLabel':{'cn':'国服','jp':'日服','unknown':'服务器未知'}.get(meta.get('server'),str(meta.get('server') or '服务器未知')) + (f" · {meta['provider']}" if meta.get('provider') else ''),
            'syncLabel':label,'footer':f'RTLink · AI v2 · {label}（北京时间）',
            'scoreRows':unique_score_rows(analysis.get('profileScoreRows',records)),
            'configurations':configuration,'improvement':improvement,
            'strongest':ranked[0] if ranked else empty,'weakest':ranked[-1] if ranked else empty,
            'history':analysis.get('configurationHistory') or []}
