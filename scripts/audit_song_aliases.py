"""Check every bundled identity and export the complete searchable review table."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from song_alias import load_aliases, normalize
from storage import load_charts, load_dan_courses


def audit():
    aliases = load_aliases(ROOT / "resource/aliases.v1.json.gz")
    identities = json.loads((ROOT / "scripts/data/song_names.json").read_bytes())
    charts = load_charts(ROOT / "resource/charts.v1.json.gz")
    dan = load_dan_courses(ROOT / "resource/dan_courses.v1.json.gz", charts)
    curated = json.loads((ROOT / "scripts/data/song_alias_review.json").read_bytes())
    rows, conflicts = [], []
    duplicate_groups = [
        {137, 1259},
        {141, 1258},
        {191, 1266},
        {323, 1262},
        {433, 1265},
        {450, 1257},
        {527, 1261},
        {750, 1260},
        {939, 1263},
        {1146, 1264},
        {1032, 1429},
    ]
    different_groups = [
        {153, 433, 1265},
        {185, 408},
        {373, 511},
        {523, 766},
        {930, 1143},
        {50, 964},
        {329, 330},
        {115, 116, 542},
    ]
    short_groups = [
        {252, 338},
        {371, 372},
        {888, 1449},
        {1082, 1187},
        {1450, 1451, 1452},
    ]
    variants = [{186, 1478}, {1411, 1479}, {1170, 1480}, {1369, 1481}]
    for key, keys in sorted(aliases["ambiguous"].items()):
        ids = {int(value.partition("|")[0]) for value in keys}
        titles = [identities["songs"][str(sid)]["title"] for sid in sorted(ids)]
        if any("双打" in title for title in titles):
            category = "通常版/双打版"
        elif any(ids <= group for group in variants):
            category = "通常版/异变版（标点折叠或省略版本后重名）"
        elif any(ids <= group for group in duplicate_groups):
            category = "同名多游戏ID（保留独立记录）"
        elif any(ids <= group for group in different_groups):
            category = "不同曲/不同版本同名（禁止合并）"
        elif any(ids <= group for group in short_groups):
            category = "简称/系列/篇章省略后重名"
        else:
            raise ValueError(f"Unreviewed collision: {key}: {ids}")
        conflicts.append(
            {
                "key": key,
                "songIds": sorted(ids),
                "titles": titles,
                "category": category,
                "decision": "保留全部候选；用完整版本名或ID消歧",
            }
        )
    for sid, song in identities["songs"].items():
        items = [
            item
            for key, item in aliases["songs"].items()
            if key.partition("|")[0] == sid
        ]
        if not items:
            raise ValueError(f"song missing alias entry: {sid}")
        names = {}
        for item in items:
            if item["names"][0] != song["title"]:
                raise ValueError(f"CN display mismatch: {sid}")
            for name in item["names"] + item["aliases"]:
                if not any(
                    key.partition("|")[0] == sid
                    for key in aliases["index"].get(normalize(name), [])
                ):
                    raise ValueError(f"name unreachable: {sid}: {name}")
                names.setdefault(name, set()).update(item["name_sources"].get(name, []))
        rows.append(
            {
                "id": int(sid),
                "title": song["title"],
                "titleJa": song["titleJa"],
                "cnStatus": song["cnStatus"],
                "levels": song["levels"],
                "names": {name: sorted(sources) for name, sources in names.items()},
                "conflicts": [c["key"] for c in conflicts if int(sid) in c["songIds"]],
                "rated": any(s == int(sid) for s, _ in charts),
            }
        )
    dan_rows = []
    for course in dan["courses"]:
        for song in course["songs"]:
            sid, level = song["song_no"], song["level"]
            identity = identities["songs"].get(str(sid), {})
            meta = identity.get("levels", {}).get(str(level), {})
            notes = meta.get("totalNotes")
            if (
                song["mapping_evidence"].startswith("title+level+notes")
                and notes != song["total_notes"]
            ):
                raise ValueError(f"dan notes mismatch: {sid}|{level}")
            dan_rows.append(
                {
                    "year": course["year"],
                    "region": course["region"],
                    "rank": course["rank"],
                    "order": song["order"],
                    "sourceTitle": song["title"],
                    "displayTitle": identity.get("title"),
                    "songNo": sid,
                    "level": level,
                    "notes": song["total_notes"],
                    "catalogNotes": notes,
                    "candidates": song["song_no_candidates"],
                    "status": song["mapping_status"],
                    "evidence": song["mapping_evidence"],
                }
            )
    report = {
        "version": identities["dataVersion"],
        "sources": identities["sources"],
        "summary": {
            "songs": len(rows),
            "identityCharts": len(aliases["songs"]),
            "nameEntries": sum(
                len(i["names"]) + len(i["aliases"]) for i in aliases["songs"].values()
            ),
            "currentCnSongs": sum(row["cnStatus"] == "current" for row in rows),
            "collisionKeys": len(conflicts),
            "sourceDifferences": len(identities["sourceDifferences"]),
            "excludedSourceIds": len(identities["excludedSourceEntries"]),
            "danEntries": len(dan_rows),
            "danEvidence": dict(Counter(row["evidence"] for row in dan_rows)),
        },
        "sourceDifferences": identities["sourceDifferences"],
        "excludedSourceEntries": identities["excludedSourceEntries"],
        "removedAliases": curated["removed"],
        "conflicts": conflicts,
        "songs": rows,
        "dan": dan_rows,
        "ratingResourceSha256": hashlib.sha256(
            (ROOT / "resource/charts.v1.json.gz").read_bytes()
        ).hexdigest(),
    }
    return report


def render(report):
    # Data stays local; user-entered search text is never interpreted as HTML.
    payload = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    return (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>RTLink 曲名映射审核 · __AUDIT_DATE__</title><style>
:root{font:15px/1.6 system-ui,'Microsoft YaHei',sans-serif;color:#263444;background:#f3f5f8}body{max-width:1560px;margin:35px auto;padding:0 24px}h1{font-size:28px;margin-bottom:6px}p{max-width:1100px}.cards{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}.card{background:white;padding:14px 22px;border-radius:10px;min-width:125px}.card strong{font-size:25px;display:block;color:#175879}nav{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}button,input,select{font:inherit;padding:9px 14px;border:1px solid #c9d4df;border-radius:6px;background:white}button{cursor:pointer}button.active{background:#175879;color:white}input{min-width:330px}table{width:100%;border-collapse:collapse;background:white;font-size:14px}th,td{padding:12px;text-align:left;border-bottom:1px solid #dde3ea;vertical-align:top}th{position:sticky;top:0;background:#e7eef4;white-space:nowrap}small{color:#677887}.names{max-width:640px;overflow-wrap:anywhere}.tag{display:inline-block;border-radius:4px;padding:0 5px;margin:2px;background:#edf3f8}details{margin-top:5px}summary{cursor:pointer;color:#175879}.scroll{overflow:auto}a{color:#175879}footer{margin:25px 0;color:#677887}.notice{background:#fff7de;border-left:4px solid #c59b34;padding:12px 18px}
</style><h1>RTLink 曲名与谱面映射审核</h1><small>__AUDIT_DATE__ · 本地公开资料快照 · 每个名称均保留来源</small>
<p>国服当前曲名优先；下架曲保留已有国服译名。日文、ESE 罗马字、菌菌写法、段位写法及经整理的短名共同用于搜索。<b>名称/ID 可查询不代表已有 AI 评级数据。</b></p>
<div class="notice">审核范围：全量 ID、名称可达性、显示优先级、全部冲突键与段位物量核对；口语别名仅做语义和冲突复核，未宣称全部具有外部权威出处。国服公告图尚未直接复核。Sakura 下架状态可能滞后于当日开放，不据此修改课程。</div>
<div class="cards" id="cards"></div><nav id="tabs"></nav><input id="q" aria-label="搜索名称或ID" placeholder="搜索 ID、国服名、日文、罗马字或简称"><select id="status" aria-label="国服状态"><option value="">全部状态</option><option value="current">当前国服</option><option value="archive">归档/下架</option><option value="unknown">未确认国服状态</option></select><p id="count"></p><div class="scroll"><table><thead id="head"></thead><tbody id="body"></tbody></table></div><footer>数据来源：<a href="https://viewer.sakura-bot.cn/api/content/songs">Sakura 公共曲库</a> · <a href="https://kinoko.zorua.cn/api/scores/catalog?schema_version=3">菌菌公共曲库</a> · <a href="https://ese.tjadataba.se/ESE/ESE.git">ESE TJA</a> · 仓库评级与段位快照。完整指纹和审核记录见同目录 JSON。</footer>
<script id="data" type="application/json">"""
        + payload
        + r"""</script><script>
const data=JSON.parse(document.getElementById('data').textContent);let tab='songs';const labels={songs:'完整名称表',dan:'段位映射 501 条',conflicts:'全部名称冲突',sourceDifferences:'来源差异',removedAliases:'移除/纠正别名',excludedSourceEntries:'排除的站内编号'};
const el=id=>document.getElementById(id),statusLabel={current:'当前国服',archive:'归档/下架',unknown:'未确认',other:'其他'};
for(const [k,t] of [['songs','歌曲'],['currentCnSongs','当前国服'],['identityCharts','鬼/里身份'],['nameEntries','名称写法'],['collisionKeys','冲突键']]){const d=document.createElement('div');d.className='card';const n=document.createElement('strong');n.textContent=data.summary[k];d.append(n,t);el('cards').append(d)}
for(const [key,label] of Object.entries(labels)){const b=document.createElement('button');b.textContent=label;b.onclick=()=>{tab=key;draw()};b.dataset.key=key;el('tabs').append(b)}
function cell(tr,text){const td=document.createElement('td');td.textContent=text??'—';tr.append(td);return td}
function draw(){document.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.key===tab));const q=el('q').value.toLocaleLowerCase().trim();const rows=data[tab].filter(r=>(!q||JSON.stringify(r).toLocaleLowerCase().includes(q))&&(tab!=='songs'||!el('status').value||r.cnStatus===el('status').value));el('head').replaceChildren();el('body').replaceChildren();el('count').textContent=`${rows.length} / ${data[tab].length} 条 · 按 ID 保留身份，歧义不自动合并`;const headers={songs:['ID / 状态','优先显示 / 日文','名称与来源','评级 / 冲突'],dan:['届别 / 地区 / 段位','曲序 / 曲名','ID / 候选','难度 / 物量','映射证据'],conflicts:['归一化名称','ID / 曲名','分类','处理'],sourceDifferences:['ID','Sakura','菌菌','处理'],removedAliases:['原 ID','名称','移除原因'],excludedSourceEntries:['来源编号','名称','原因']}[tab];const hr=document.createElement('tr');for(const h of headers){const th=document.createElement('th');th.textContent=h;hr.append(th)}el('head').append(hr);
for(const r of rows){const tr=document.createElement('tr');if(tab==='songs'){cell(tr,r.id+' · '+statusLabel[r.cnStatus]);cell(tr,r.title+'\n'+(r.titleJa===r.title?'':r.titleJa));const td=cell(tr,'');td.className='names';for(const name of Object.keys(r.names)){const sp=document.createElement('span');sp.className='tag';sp.textContent=name;sp.title=r.names[name].join(' / ');td.append(sp)}const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='查看逐名来源';details.append(summary);for(const [n,src] of Object.entries(r.names)){const d=document.createElement('div');d.textContent=n+' ← '+src.join(' / ');details.append(d)}td.append(details);cell(tr,(r.rated?'含评级谱面':'仅曲目身份')+(r.conflicts.length?' · '+r.conflicts.length+' 个歧义名称':''))}else if(tab==='dan'){cell(tr,[r.year,r.region,r.rank].join(' / '));cell(tr,r.order+'. '+r.displayTitle+' ('+r.sourceTitle+')');cell(tr,r.songNo+' / '+r.candidates.join(', '));cell(tr,r.level+' / '+r.notes+'，曲库核对 '+(r.catalogNotes??'未提供'));cell(tr,r.evidence+' · '+r.status)}else if(tab==='conflicts'){cell(tr,r.key);cell(tr,r.songIds.map((v,i)=>v+': '+r.titles[i]).join(' / '));cell(tr,r.category);cell(tr,r.decision)}else if(tab==='sourceDifferences'){cell(tr,r.songNo);cell(tr,r.sakura);cell(tr,r.kinoko);cell(tr,'同一 game_id，保留来源写法和版本标识')}else if(tab==='removedAliases'){cell(tr,r.songNo);cell(tr,r.name);cell(tr,r.reason)}else{cell(tr,r.sourceId);cell(tr,r.title);cell(tr,'其他歌曲栏站内编号，未获游戏 ID 确认')}el('body').append(tr)}}
el('q').oninput=draw;el('status').onchange=draw;draw();</script></html>"""
    ).replace("__AUDIT_DATE__", str(report["version"])[:10])


if __name__ == "__main__":
    report = audit()
    out = ROOT / ("docs/song-alias-audit-" + str(report["version"])[:10])
    out.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    out.with_suffix(".html").write_text(render(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
