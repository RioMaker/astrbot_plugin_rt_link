"""Render the reviewed CN backfill as an offline searchable acceptance table."""

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    review = json.loads((ROOT / "scripts/data/cn_constant_backfill.json").read_bytes())
    result = json.loads(
        (ROOT / "docs/cn-constant-backfill-2026-10-16.json").read_bytes()
    )
    identities = json.loads((ROOT / "scripts/data/song_names.json").read_bytes())[
        "songs"
    ]
    charts = {
        (c["id"], c["level"]): c
        for c in json.loads(
            gzip.decompress((ROOT / "resource/charts.v1.json.gz").read_bytes())
        )
    }
    rows = []
    for item in review["charts"]:
        chart = charts.get((item["id"], item["level"]), {})
        rows.append(
            {
                **item,
                "title": identities[str(item["id"])]["title"],
                "aiConstant": (chart.get("feature") or {}).get("aiConstant"),
                "referenceConstant": (chart.get("public") or {}).get("constant"),
                "cnStatus": identities[str(item["id"])]["cnStatus"],
            }
        )
    cn_keys = [
        (int(sid), int(level))
        for sid, song in identities.items()
        for level, meta in song["levels"].items()
        if level in ("4", "5") and meta.get("cnAvailable")
    ]
    summary = {
        "reviewed": len(rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "cnSongs": sum(s["cnStatus"] == "current" for s in identities.values()),
        "cnCharts": len(cn_keys),
        "cnMissingAI": sum(not charts.get(k, {}).get("feature") for k in cn_keys),
        "retiredReferences": sum(
            bool(r.get("retiredReference")) for r in result["added"]
        ),
    }
    result.update(summary=summary)
    (ROOT / "docs/cn-constant-backfill-2026-10-16.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    data = json.dumps({"rows": rows, "summary": summary}, ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    html = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>国服定数补齐审计 · 2026-10-16</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#172033;font:15px/1.6 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1450px;margin:auto;padding:32px}h1{font-size:27px;margin:0 0 8px}.muted{color:#5c677d}.cards{display:flex;gap:14px;flex-wrap:wrap;margin:22px 0}.card{background:white;border:1px solid #dbe1eb;border-radius:10px;padding:13px 22px;min-width:160px}.card b{display:block;font-size:28px;color:#145e87}input,select{font:inherit;padding:10px;border:1px solid #bac6d7;border-radius:7px}input{width:min(500px,100%)}.controls{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}.table{overflow:auto;background:white;border:1px solid #dbe1eb;border-radius:10px}table{border-collapse:collapse;width:100%;min-width:1000px}th,td{text-align:left;padding:12px;border-bottom:1px solid #e2e7ef;vertical-align:top}th{background:#eaf0f7;white-space:nowrap}td:nth-child(2){min-width:210px}td:last-child{max-width:440px;overflow-wrap:anywhere}details{font-size:13px}.good{color:#087a53}.pending{color:#966013}code{font-size:12px}a{color:#176388}footer{margin-top:20px;font-size:13px}
</style><main><h1>国服定数补齐审计</h1><div class="muted">2026-10-16 · 原始 98 张逐谱核对 · AI v2 冻结模型推理，未重新训练</div>
<div class="cards" id="cards"></div><p>原有 1327 张 AI 特征完整保留。6 张明确双打按用户要求暂缓；4 张需要 P1 映射复核的谱面暂缓。LUMINΔ 鬼谱与技神暗鬼鬼谱缺少 TJA；用户提供的技神暗鬼里谱已纳入。</p>
<p class="muted">本表的定数为 AI v2 定数。参考 OurTaiko-v1 保持原值，缺失不估填；本次新增的是 AI v2 定数。国服状态依据公开目录及有日期的更新/下架公告修正，不代表机台实测。</p>
<div class="controls"><input id="q" placeholder="搜索 ID、曲名、来源、指纹…"><select id="status"><option value="">全部处理状态</option><option value="verified">已补齐</option><option value="deferred-double">双打暂缓</option><option value="deferred-p1-mapping">P1 映射待复核</option><option value="missing-tja">缺 TJA</option></select><span id="count"></span></div>
<div class="table"><table><thead><tr><th>ID / 难度</th><th>国服曲名</th><th>处理状态</th><th>AI / 参考定数</th><th>物量（原评级 → 已核对）</th><th>来源与逐谱证据</th></tr></thead><tbody id="rows"></tbody></table></div>
<footer>关联文件：scripts/data/cn_constant_backfill.json · scripts/data/cn_catalog_overrides.json · docs/cn-constant-backfill-2026-10-16.json<br>源码不含播放器音频；TJA 原字节及 SHA-256 可复核。暂缓条目未新增定数或单人分析。</footer></main>
<script type="application/json" id="data">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),el=id=>document.getElementById(id),labels={'verified':'已补齐','deferred-double':'双打暂缓','deferred-p1-mapping':'P1 映射待复核','missing-tja':'缺 TJA'};
for(const [n,v] of [['已补齐',data.summary.statuses.verified],['暂缓',data.summary.statuses['deferred-double']+data.summary.statuses['deferred-p1-mapping']],['缺 TJA',data.summary.statuses['missing-tja']],['国服单曲 / 鬼里谱面',data.summary.cnSongs+' / '+data.summary.cnCharts]]){const c=document.createElement('div');c.className='card';const b=document.createElement('b');b.textContent=v;c.append(b,document.createTextNode(n));el('cards').append(c)}
function draw(){const q=el('q').value.trim().toLocaleLowerCase(),status=el('status').value;const rows=data.rows.filter(r=>(!status||r.status===status)&&(!q||JSON.stringify(r).toLocaleLowerCase().includes(q)));el('rows').replaceChildren();el('count').textContent=rows.length+' / '+data.rows.length+' 张';for(const r of rows){const tr=document.createElement('tr');for(const text of [r.id+' / '+(r.level===4?'鬼':'里'),r.title+' · '+r.stars+'★',labels[r.status],(r.aiConstant??'—')+' / '+(r.referenceConstant??'—'),(r.ratingNotes??'未收录')+' → '+(r.totalNotes??'待核对')]){const td=document.createElement('td');td.textContent=text;tr.append(td)}tr.children[2].className=r.status==='verified'?'good':'pending';const td=document.createElement('td');td.textContent=r.reason||r.review||(r.bound?'已有绑定，指纹和物量复核通过':'按来源、难度与物量核对');const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='查看证据';details.append(summary);const pre=document.createElement('pre');pre.style.whiteSpace='pre-wrap';pre.textContent=JSON.stringify({source:r.source,path:r.path,sha256:r.sha256,fingerprintV4:r.fingerprintV4,fingerprintV5:r.fingerprintV5,warnings:r.warnings,reviewUrl:r.reviewUrl},null,2);details.append(pre);td.append(details);tr.append(td);el('rows').append(tr)}}el('q').oninput=draw;el('status').onchange=draw;draw();
</script></html>""".replace("__DATA__", data)
    (ROOT / "docs/cn-constant-backfill-2026-10-16.html").write_text(html, "utf-8")
    resources = [
        p
        for p in (ROOT / "resource").iterdir()
        if p.name.endswith(".json.gz")
        or p.name in ("cn-tja-20261016.zip", "chart-library-20261014.zip")
    ]
    manifest = {
        "schemaVersion": 1,
        "dataVersion": review["version"],
        "runId": "cn-constant-backfill-20261016",
        "baselineCommit": "f117b2298958758613bace996d6ff146ee9f5dad",
        "baselineChartsSha256": review["baselineChartsSha256"],
        "primaryRating": {
            "modelId": "taiko-signal-rhythm-v2-2026-08-05",
            "retrained": False,
            "existingFeaturesPreserved": 1327,
            "addedFeatures": summary["statuses"]["verified"],
            "modelWeightsSha256": review["model"]["modelSha256"],
        },
        "summary": summary,
        "reviews": [
            "scripts/data/cn_constant_backfill.json",
            "scripts/data/cn_catalog_overrides.json",
            "docs/cn-constant-backfill-2026-10-16.json",
        ],
        "resourcesSha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(resources)
        },
        "liveValidation": "Offline model replay, packaged source and runtime tests only; no AstrBot/QQ deployment",
    }
    (ROOT / "resource/data_refresh.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    build()
