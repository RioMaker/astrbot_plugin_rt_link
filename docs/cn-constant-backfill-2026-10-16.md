# 2026-10-16 国服定数补齐

本次核对原清单的 98 张谱面，补齐 **86 张 AI v2 定数**：已有 TJA 绑定的 47 张中完成 42 张、双打暂缓 5 张；其余 51 张完成 44 张。最终国服目录为 1131 首、1398 张鬼／里谱面，其中 1386 张具备 AI 定数。该目录以公开来源及已确认的状态修正为准，未进行机台实测。

[可搜索的逐谱审计](cn-constant-backfill-2026-10-16.html)包含 ID、难度、物量、定数、源文件、模型解析指纹及选源说明。[机器可读结果](cn-constant-backfill-2026-10-16.json)与[构建输入](../scripts/data/cn_constant_backfill.json)分开保存。

## 剩余 12 张

| 原因 | 谱面 |
| --- | --- |
| 按用户要求暂缓双打，6 张 | 双龙之乱鬼；Garakuta Doll Play 鬼／里；Brave Sword, Braver Soul 鬼；KAGEKIYO 鬼；Many wow bang! 鬼（均为独立【双打】ID） |
| P1 映射仍待复核，4 张 | インベーダーインベーダー鬼、LINDA LINDA 鬼、旋风ノ舞【天】里、DAJARE de OSHARE 鬼 |
| 缺少 TJA，2 张 | LUMINΔ 鬼、技神暗鬼鬼 |

P1 组并未直接判为独立双打曲目：现有单人解析结果与目标物量不符，匹配候选在 P1 区块中；在用户暂停双打分析后，本次没有抽取 P1 或改写 COURSE。后续需确认其国服单人映射。用户提供的 `resource/技神闇鬼.zip` 只有里谱，10 星、999 音符，AI 定数为 **10.8896**；保留用户原包，仅将 TJA 原字节纳入构建源包，音频未纳入发布资源。

## 数据与推理

- 评级资源从 1393 增至 1421 张；AI 特征从 1327 增至 1413 张。新增 28 张条目，补全 58 张现有条目，修正其中 12 张的音符数。
- 使用现有 `feature-profile-model.v2.joblib`，权重 SHA-256 为 `14aa800b2131398af90f80cef227567ebc6dc256f3fc050e22ebef3813e71f79`。没有训练、换权重或修改 Rating 公式。
- 模型原始训练数据 SHA-256 为 `6795ef6ae5f5833b0b4fa70e9fed45a387e6540c541a54c67d62b32f2c9595f2`，保留原 `validate_model` 的数据集哈希、解析器版本、字段顺序与输入维度校验。1327 个旧定数回放全部一致，全部旧 AI 特征另有整体哈希回归保护。
- 推理输入使用 parser-v4 原始特征，并遵照原数据集构建器补充 `star_level` 和 `course_is_edit`，再按冻结模型的 446 维字段顺序计算。分析库及 BPM7 配置继续使用 parser-v5；两种解析指纹均记录。
- 《拔萝卜》TJA 是旧星级 5、223 音符，国服新版为 6 星；依据[版本表](https://wikiwiki.jp/taiko-fumen/収録曲/おに/拔蘿蔔)保留原 TJA 字节，推理的 `star_level` 使用经核对的国服 6 星。
- 《七彩ボタン》拒绝 Sakura 包中标注 VitaMS 的版本，选用 ESE AC16 版本；同音符数不能单独证明同一谱面。原曲与 VitaMS 的版本差异见[谱面资料](https://wikiwiki.jp/taiko-fumen/収録曲/おに/七彩ボタン)。
- OurTaiko-v1 参考定数完整保留，本次没有估填参考定数。代码同时拒绝将旧物量的参考画像用于新物量；本批涉及物量修正的条目原本就没有参考画像，因此没有撤下任何已有参考定数。
- 3299 份谱面分析、1621 个 ID／难度绑定已封装回原发布 ZIP 文件名；保留旧 3255 份分析，仅增加 44 份已核对分析。新增 86 张配置与连打数据，保留旧配置，并按运行时顺序重算全良理论上限。

源 TJA 来自已审核的 ESE `fa2374283a11e0bdac4a7ba23aafc0d5317540e5`、新快照 `cb01aa31e7ff0edb4a61b759d8b7c791a387dcd6`、Sakura 按游戏 ID 提供的谱面包及用户提供的技神暗鬼里谱。所有发布源字节位于 `resource/cn-tja-20261016.zip`，逐文件 SHA-256、来源 URL、版本与选源理由在构建输入中。

## 国服收录状态

依据[官方 2026-10-14 公告](https://www.bilibili.com/opus/1257129643294588951)，将 1447、1448、1449、1464、1465、1502 改为国服当前收录，并采用国服显示名。937《向夜晚奔去》依[更新记录](https://wikiwiki.jp/taiko-fumen/作品/新AC中国版/アップデート履歴)标为 2026-08-19 下架。旧名称仍保留来源，未覆盖身份。

修正在 `scripts/data/cn_catalog_overrides.json` 中，`build_song_names.py` 会再次应用。每个难度另有 `cnDifficultyListed` 与 `cnAvailable`，避免因歌曲在架而将仅海外存在的里谱计为国服收录。曲目级 `cnStatus` 保持原有兼容语义。

模型标识不变，新增 `catalogVersion=taiko-signal-rhythm-v2-2026-08-05+cn-2026-10-16.1` 记录数据变化。画像资源版本及哈希随数据更新，旧缓存会因配置资源哈希不同而重新计算；已有历史保留原版本，不重写玩家数据库。

## 复现与验证

维护缓存为 `cache/constant-backfill-20261016/`（Git 忽略）。其中 `before.zip` 是修改前静态资源和 `song_names.json` 快照，基线提交为 `f117b2298958758613bace996d6ff146ee9f5dad`。外部模型目录只读，未修改其源代码、数据集或权重。

构建顺序如下，`MODEL_ROOT` 指向具有原权重、原训练数据及 `ml`、`taiko_model` 代码的模型工程。须先核对源与模型哈希，不能用其他模型替代。

```powershell
.venv/Scripts/python.exe scripts/backfill_cn_constants.py --baseline cache/constant-backfill-20261016/before.zip --model-root MODEL_ROOT
.venv/Scripts/python.exe scripts/build_dan_courses.py
.venv/Scripts/python.exe scripts/build_aliases.py
.venv/Scripts/python.exe scripts/backfill_cn_constants.py --baseline cache/constant-backfill-20261016/before.zip --model-root MODEL_ROOT --library-only
.venv/Scripts/python.exe scripts/audit_cn_constants.py
.venv/Scripts/python.exe -m pytest test -q
```

名称目录重建使用原有 `build_song_names.py` 入口和已保存的 Sakura／Kinoko／ESE 输入；本次复核结果会自动应用。推理构建器只新增本清单内的缺失特征，拒绝替换已存在的 AI 特征。快照、源归档与模型均校验哈希后使用。

`pytest test -q`：**322 passed**。验收覆盖真实发布 ZIP 的离线安装、全部 86 张按 ID 查询、TJA 音符数与运行库一致、完整旧特征哈希、国服状态修正、全良画像理论上限复算及既有功能回归。发布资源哈希、源归档哈希及构建脚本哈希均核对通过，审计页的筛选与显示已在本地浏览器核对。没有推送、部署或进行真实 AstrBot／QQ 调用。
