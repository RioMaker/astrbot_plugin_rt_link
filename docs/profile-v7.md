# Profile v0.14 数据与渲染

`profile_image.py` 是正式 Pillow 渲染入口；`profile_theme.py` 管理图形和素材，`profile_data.py` 管理评分数据契约。`/rtlink` 和 `/rtlink profile` 走同一个服务入口，`/rtlink rating` 保留原报告。所有图片本地生成，无远端渲染、固定玩家或开发机路径。

## 数据口径

- 概况使用已同步的所有表/里成绩，包含未达评级门槛的谱面，按 `(id,level)` 去重；皇冠优先级为全良、全连、通过，评价同样互斥。
- BEST 20 使用可评级谱面的单谱 Rating 降序；皇冠和评价图标分别来自历史最佳状态与 `bestScoreRank`。图标素材位于 `resource/profile/`，取用户提供的原始皇冠、判定和评价图集首列静态帧。
- 配置重分档来自 TJA 段落 BPM，未按整曲平均 BPM 近似归类。`profile_configurations.v1.json.gz` 只替换配置所需的 `rhythmProfile.cells/arrangementCells`，原 AI 定数、七维和详细报告的旧分档保持原算法。
- 分母使用所有可计算谱面全良的单谱 Rating，经原 `calculate_rhythm_ability` 同样的筛选、权重和聚合得出。当前资源含 1,327 张特征谱面、116 个实际存在的配置组合；详情固定展示 18 × 7 格，不存在的组合显示空值。
- 综合环配色按未取整评分的 6、10、15 分界；配置及卡片比例颜色使用统一评价门槛。卡片实际评价图标独立于比例色。

## 历史与兼容

缓存契约升至 6，老缓存按需自动同步。SQLite 添加 `configuration_snapshots`，不重写旧成绩或旧历史。新历史保留 zlib 压缩的评分输入及配置状态，按最近一份相同身份/版本输入哈希去重；当前阶段采用每次变化的完整压缩快照，尚未采用歌曲增量/定期检查点。查看报告不写历史。`catalog_versions/<sha256>.json.gz` 每个资源版本只归档一份。

历史查询同时过滤 QQ、游戏玩家、服务器、数据源、算法标识、配置版本和两个资源哈希。详情显示最近 90 次记录；只有一个记录时不画趋势。缺失值保留 `NULL` 及原因，线条在缺失处断开。升级版本后积累新的同版本基线，旧分档不重命名接续。

## 资源重建

部署只需随插件发布的压缩资源，不需要 TJA 或模型工程。维护者可用参数化脚本重建：

```powershell
python scripts/build_profile_configurations.py --model-root <模型工程> --ese-root <ESE目录> --version <发布版本> --output <暂存目录>
```

脚本使用模型工程 `ml/artifacts/parser-v5/mapping-report.v1.json`，在独立进程重分档，逐谱核对 fingerprint 与 totalNotes；缺图或不一致时禁止发布。检查暂存资源与 manifest 后一同更新发布文件；修改配置算法须更新 `CONFIGURATION_ALGORITHM` 并重建基线。原始 TJA 与玩家原始缓存不加入仓库。

## 本地验证（2026-09-20）

- `python -m pytest test -q`：246 项通过，覆盖旧命令、同步、SQLite 迁移、配置理论满分复算、缺失值、历史去重及身份/版本隔离。
- 使用本地 2026-08-14 真实缓存回放服务同步与渲染：1,390 张表/里成绩、1,314 张可评级谱面、8 首推荐；正式 Profile 为 1440 × 4350，BEST 20 卡片区域与获确认的 V7 逐像素一致。
- 参数化重建脚本再次核对全部 1,327 张 TJA 后，压缩资源逐字节一致；SHA-256 为 `cb077a40e22dbd063b8f77aaf693a2c2fea2ea7ca7580cee54f971d6e890ac44`。逐谱来源证据存于 `profile_configurations.provenance.json.gz`。
- 以上是本地缓存、模拟 API 和本地渲染验证；未执行真实菌菌 API 同步或生产 AstrBot 部署。
