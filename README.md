# ForeGate Tennis：免费数据网球胜率模型

已完成可运行的 ATP/WTA 单打赛前胜负模型，含训练好的 JSON 快照、免费数据下载器、时间顺序回测、命令行和 HTTP 接口。下方模型成绩来自截至 2026-10-24 的离线验证；生产快照日期以 `/health` 为准。源码仓库为 [ForegatePrediction/FG-tennis-prediction](https://github.com/ForegatePrediction/FG-tennis-prediction)，与此前各预测模型仓库一致，使用公开设置。2026-10-26 已部署到 [生产网关](https://gateway.watchlived.cc/health)，启用免费赛程定时采集及 GitHub Release 模型同步；维护方式见[生产部署与维护](docs/生产部署.md)。这不表示已覆盖全部 Poly 网球赛事。

2026-10-26 已补齐逐盘制、逐层级、双方正负让分回测和精确比分单选成绩；增加分盘比分候选、刷新暂存与失败回滚。当前结果及验收见[代码优化与验证完整性](docs/代码优化与验证完整性-2026-10-26.md)，优化前记录见 [V2 模型报告](docs/大小分、完赛与扩展玩法-v2-2026-10-26.md)。

生产状态、真实赛事数量及调用核验见[生产上线验收](docs/生产上线验收-2026-10-26.md)；早期报告中的“未部署”描述保留为当时记录。

模型采用总体 Elo、场地 Elo、排名与积分、近期表现、历史发接发球统计等特征，由正则化逻辑回归输出概率，并使用独立年度做温度校准。ATP、WTA 分开训练。**不需要付费 API、API Key 或赔率数据。** 历史交锋已实现并参与对照实验，但本轮验证没有带来提升，因此成品展示交锋记录，不把它计入最终概率。

| 独立测试：2025 至可用截止日 | ATP | WTA |
| --- | ---: | ---: |
| 测试场次 | 4,748 | 4,541 |
| 模型准确率 | 66.62% | 67.01% |
| 基础 Elo 准确率 | 64.74% | 65.32% |
| 模型 Log loss，越低越好 | 0.61125 | 0.60385 |
| 基础 Elo Log loss | 0.64246 | 0.62513 |

以上是本项目实际运行结果，属于离线检验，不代表未来比赛的保证准确率。完整方法、研究依据、数据缺口及分场地结果见 [研究与验证报告](docs/研究与验证报告.md)。机器可读结果在 `reports/*-backtest.json`。

## 直接预测

Foregate 原 PRD 的 GET 直连接入已提供本地实现：

```bash
python3 server.py --demo --port 8105
# Open http://127.0.0.1:8105/demo
```

Demo 复用“一次 GET 整场结果 → 按玩法取结果 → AI 浮层”的交互，含 ATP/WTA、11 类玩法、盘口切换、繁中／英文／越南文及降级展示。Demo 对阵是明确标记的合成测试，概率由本地模型计算，不是真实赛程。普通模式不开放 Demo。

Foregate GET 支持只传两名球员：`https://gateway.watchlived.cc/predict?type=tennis&tour=wta&a=Qinwen%20Zheng&b=Aryna%20Sabalenka&lang=zh`。不要求具体联赛或真实赛程，`eventSlug` 可选；存在已审核赛事时自动补充其背景和实际盘口，否则返回明确标注假设的球员基础预测。姓名兼容大小写、空格、连字符、常见标点和重音；仍须唯一完整姓名、内部 ID 或已核实别名。缺少场地时汇总硬地／红土／草地场景，缺少盘制默认三盘两胜并返回 `assumptions`。该缺省背景路径尚未独立回测，不套用下方准确率；未知球员仍明确不可用。请求、严格赛事模式及前端传值见 [GET 接入与联调说明](docs/Foregate-GET接入与联调.md)，修改与兼容验证见 [按球员预测与姓名兼容](docs/按球员预测与姓名兼容-2026-10-26.md)。

进入本项目文件夹后，Python 3.9+ 即可运行；预测不需要安装第三方包。本地交付包已包含 `models/current.json`；Git 仓库不保存训练快照及原始历史数据。从源码仓库取得项目时，需要先执行下方的下载和训练步骤生成快照，或从成功的 GitHub Actions 运行下载 `tennis-model-*` 制品并解压到项目根目录。

```bash
python3 cli.py health
python3 cli.py players --tour atp --query Alcaraz
python3 cli.py predict --tour atp --a 'Carlos Alcaraz' --b 'Alexander Zverev' --surface Hard
python3 cli.py predict --tour wta --a 'Aryna Sabalenka' --b 'Iga Swiatek' --surface Clay
```

这些是两名球员的假设对阵示例，不表示实际赛程。可以传完整英文名或本站球员 ID。姓名需要完整且唯一，模糊匹配只用于搜索，避免给同姓球员错误地合并历史。

可选项：`--best-of 5` 用于男子五盘赛；`--indoor` 表示室内；`--date YYYY-MM-DD` 表示未来 14 天内的预测日期；`--rank-a` / `--rank-b` 可传经过核实的当前排名。默认排名来自最近纳入历史的比赛资料，输出始终显示观察日期；覆盖排名时会清空对应的旧积分，避免把新排名和旧积分混用。

输出包括双方概率、排名日期、总体 Elo、场地样本量、交锋战绩、模型贡献项、数据来源和缺失提醒。模型不提供无依据的伤病判断。低样本球员、超过 60 天的球员资料、超过 3 天的旧快照会提醒。

## HTTP 接口

```bash
python3 server.py --port 8105
```

默认仅监听本机 `127.0.0.1:8105`，适合由现有网关转发。

| 路径 | 参数与用途 |
| --- | --- |
| `/health` 或 `/ping` | 快照日期、源检查日期、球员数量、是否过期 |
| `/players?tour=atp&q=Alcaraz` | 搜索球员和对应 ID |
| `/predict?tour=atp&a=A0E2&b=Z355&surface=Hard&best_of=3` | 返回比赛胜负概率 |
| `/predict/market` | 实验性盘胜者、让局／让盘、大小局／大小盘、精确比分条件概率 |
| `POST /predict/markets` | 一次计算全部盘口；省略 markets 时返回截图 16 项（15 项比分条件概率＋完赛历史整体概率） |
| `POST /predict/poly-event` | Gamma 事件＋核实的球员／赛事映射；按原 outcome 和 Token 顺序返回条件概率或逐项缺失原因 |
| `/predict/completion` | 不依赖球员历史的整体完赛基线；可传 tour、competition、rule_days=7/14、date |
| `POST /predict/tournament` | 调用方核实的完整单淘汰签表推演 |
| `POST /predict/tournament/market` | 指定夺冠／晋级等二元玩法，含击败高种子及目标集合至少赢一场 |
| `/coverage` | 全部 38 类玩法的能力及缺口 |

`tour` 必须是 `atp` / `wta`。`surface` 必须是 `Hard` / `Clay` / `Grass` / `Carpet`。可选 `indoor=true`、`date`、`rank_a`、`rank_b`。WTA 五盘制、未知球员、相同球员、缺失必需参数及使用当前快照回推过去比赛，会返回明确错误。

HTTP 服务把快照载入内存；刷新快照后需重启服务。健康检查超过三天未检查来源或未生成快照时返回 `degraded`。`market_validation` 匹配盘制、赛事层级、盘口参数及让分球员；缺少匹配样本时返回空值。`classification_strategy` 标记模型是否总选同一边；五盘总盘数2.5等单一结果测试会单独标记。

新增玩法的参数、逐参数回测和限制见 [全部玩法预测覆盖与模型验证](docs/网球全部玩法预测覆盖与模型验证-2026-10-26.md)。现有 11 类比分条件计算、9 类签表推演及 1 类历史整体完赛基线；17 类仍无模型。常用总局数 22.5／总盘数 2.5 的新版结果改善，但提升较小、复用了先前查看过的测试期，仍需前向验证。精确比分 Not Completed 现可用整体基线估计；自动签表同步和完整退赛结算适配仍未完成。全部返回 `contract_ready=false`，不能把类别数量当作实际赛事覆盖率。原 `/predict` 胜负模型保持兼容。

批量请求示例和截图逐项验收见 [截图盘口实现与实际覆盖](docs/截图盘口实现与实际覆盖-2026-10-26.md)：

```bash
python3 cli.py markets --request examples/markets-request.json
python3 cli.py --model models/expanded/current.json poly-event --request examples/poly-screenshot-audit-request.json
```

第一条是两名已有球员的假设对阵计算示例。第二条是截图宁波 Challenger 资格赛的历史核查，会明确返回不可预测原因；不是该比赛的赛前预测。批量盘口来自同一个比分分布，不使用 Poly 价格做模型输入，逐项提供条件、回测质量和不可用原因。

## 免费下载、训练及日更

只有训练需要 NumPy。运行环境可采用项目虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python refresh.py
python -m unittest discover -s tests -v
```

`refresh.py` 从 [TennisMyLife 公开文件索引](https://stats.tennismylife.org/api/data-files) 下载 2010 年至当前年度的 ATP/WTA 年度文件和在赛文件。已下载的过去年份缓存复用，当前年度和在赛文件每次重新检查。初次共 36 个文件，约 19 MB；预测不需要联网。

分步运行：

```bash
python fetch.py
python train.py --as-of 2026-10-24
python backtest_score.py
python train_counts.py
```

完赛基线保留已有 Poly 全量归档的明确结算标签，并通过 `python3 refresh_completion.py` 自动重查近期已结算合约；至少使用 45 天重叠窗口，各阶段设置 17 天成熟窗口。首次运行需从 [最新 Release](https://github.com/ForegatePrediction/FG-tennis-prediction/releases/latest) 恢复 `completion-checkpoint.json.gz` 到 `data/`，或先按归档训练历史种子。窗口之外的新修订或长期未结算合约可能漏记；不会把检查日期当成实际赛果日期。`/health` 显示完赛基线日期及过期状态。

可选的独立 ATP 扩展实验模型（不替换主巡回赛快照，未接入线上调度）：

```bash
python3 fetch_expanded.py
python3 train_expanded.py --as-of 2026-10-24
python3 backtest_score.py --expanded
python3 train_counts.py --expanded
python3 server.py --model models/expanded/current.json --port 8106
```

扩展源覆盖 2010 年以来 Challenger 正赛和 ATP 资格赛，数据保存在 `data/expanded/`，模型及绑定的比分配置在 `models/expanded/`。同一赛事的资格赛和正赛重赛会保留为不同比赛。**未取得 Challenger 资格赛、ITF 的独立验证数据**，即使找到球员也不会把这些赛事自动标成已覆盖。扩展测试按赛事层级分别报告；主巡回赛及扩展模型的大小局／大小盘仍为研究输出。

`python refresh.py --offline --as-of YYYY-MM-DD` 可用本地缓存完整验证刷新。流程先在暂存目录完成全部训练和报告，再带锁发布；捕获到发布失败时恢复旧文件。`python refresh.py --force-history` 重新检查历史年份修订。完整回测耗时高于仅胜负模型的流程，下载耗时取决于网络。

`.github/workflows/daily.yml` 配置为北京时间每天 13:30（UTC 05:30）执行，也可在 Actions 页面手动运行；GitHub 调度可能延迟，实际状态以 [Actions 运行记录](https://github.com/ForegatePrediction/FG-tennis-prediction/actions/workflows/daily.yml) 为准。任务恢复完赛检查点、重查近期结算，下载免费 ATP/WTA 主巡回赛数据，重新训练胜负及大小分模型，校验全部回归测试，通过后上传七天期报告制品，并发布包含校验和的模型 Release。VPS 每天 14:30 下载最新模型，通过校验后原子切换并重启网关，失败保留或恢复上一模型。赛程另由 VPS 每 15 分钟免费采集。VPS 不保存 GitHub Token，也不在约 1 GiB 内存下运行完整训练。Challenger／资格赛扩展仍需单独运行，没有加载到该生产服务。

CSV 格式错误、空历史赛季、历史赛季异常短、年度行数下降超过 5%、重复赛果冲突或来源哈希不一致时拒绝更新模型。仅明确命名的两份“进行中赛事”临时 CSV 可在字段齐全时只有表头。只有 ATP 和 WTA 都成功构建才原子替换组合快照。某个源暂时不可用时，保留旧快照并明确显示旧日期。

## 数据的实际边界

- 覆盖主巡回赛单打：四大满贯、ATP 大师赛及 500/250、WTA 1000/500/250、历史 ATP/WTA 年终总决赛。具体赛事及本次已纳入场次见 `reports/*-data-audit.json`。
- 第一版排除双打、团体赛、挑战赛、ITF、Next Gen 非标准赛制，以及退赛、弃权和不完整赛果；胜率以正常完成比赛为条件。
- 来源把 `tourney_date` 定义为赛事周。即使同一赛事存在多个日期，也不直接认定它们是准确的比赛时间。普通赛事延后七天、总决赛八天、来源标记的大师／Premier 赛事十四天、大满贯十五天，且不早于最后源日期次日，才把该赛事赛果纳入历史。这是保守的时长假设，不能替代经过核实的准确结束时间。
- 所有回测对阵都使用赛前赛事历史。因此可以日更下载，但模型不会随着同一赛事后轮结果即时调整；局数、让局和精确盘分已有实验性条件预测，具体质量限制见新增报告；滚球尚未实现。
- 截至本次构建，ATP 已接收历史中的最新源日期为 2026-10-18，保守可用日期为 10 月 21 日；WTA 最新源日期为 2026-09-30，保守可用日期为 10 月 14 日。武汉、宁波、大阪等更晚文件已下载但仍在等待窗口，预计 10 月 26 日纳入；这些源日期不能当作“最新实际比赛日”。
- 源站标注免费和 MIT，但同时说明 WTA 文件来自网上已有 CSV、可靠性低于 ATP。我们已做格式、赛果交叉核对；WTA 上游来源和完整授权链仍需进一步核验。项目没有将这点表述为已获得独立商业授权。

完整代码使用原创建模实现；参考项目和论文的链接、许可筛选及未采用方案在研究报告中列出。

## Polymarket 覆盖与免费更新核查

全部玩法见 [Poly 网球全部玩法类型核查](docs/Poly网球全部玩法类型-2026-10-26.md)：从 48,242 个历史事件提取 570,149 个独立盘口，对照 10 个官方网球专用类型及通用 moneyline，并整理旧格式、自定义盘口与逐合约结算差异。脚本为 `audit_poly_market_types.py`，汇总为 `reports/poly-tennis-market-types.json`；完整盘口索引是本地压缩制品 `reports/poly-tennis-markets.ndjson.gz`，不提交 Git。玩法发现与归类不代表现有模型已经能为这些玩法提供概率。

分类完整性以 [Poly 网球完整分类枚举（含历史）](docs/Poly网球完整分类枚举-2026-10-26.md) 为准：四大满贯、具体赛事名称、单双打、资格赛、青少年及其他赛事均分别记录。通过全部标签／系列字典、Tennis 历史游标分页和标签／系列交叉检查取得枚举；不能用当前开放赛事或 8 个 Sports 入口代表完整分类。对应脚本为 `enumerate_poly_tennis.py`、`build_poly_enumeration.py`，底表为 `reports/poly-enumeration-summary.json`、`poly-tennis-tags-all.json`、`poly-tennis-series-all.json`、`poly-tennis-competitions-all.json`。

以 Poly 为源、再映射 ForeGate 的分类研究见 [Poly 网球分类与球员映射研究](docs/Poly网球分类与球员映射研究-2026-10-26.md)。本轮开放扫描 625 个事件，其中 614 个单场比赛；已建立 8 个分类入口及 9,619 个 Poly 参与者实体的底表，包含个人记录与双打组合，不能等同于独立球员人数或模型预测覆盖。机器可读文件为 `reports/poly-taxonomy-latest.json`、`poly-event-catalog.json`、`poly-participant-registry.json`、`poly-league-mapping-input.json`、`poly-tag-inventory.json`，由 `audit_poly_taxonomy.py` 生成。

2026-10-26 核查确认：Polymarket 还包含挑战赛、资格赛、ITF、双打、温网青少年及戴维斯杯等范围，超出现有成人主巡回赛单打模型。另有比利·简·金杯分类，但本次未查询到实际事件。完整证据、免费源更新情况、时间字段疑点及扩展缺口见 [Polymarket 覆盖核查](docs/Polymarket网球覆盖与免费实时数据核查-2026-10-26.md)。

```bash
python3 audit_polymarket.py
python3 audit_free_sources.py
node capture_poly_sports.mjs 30 reports/poly-sports-probe.json
python3 -m unittest discover -s tests -p test_market_audit.py -v
```

以上均为公开只读数据调用，不需要账户或 API Key；WebSocket 探测需要 Node.js 22+。原始证据按 UTC 日期保存在 `data/market-audit/`，汇总在 `reports/poly-coverage-latest.json`、`reports/poly-league-inventory.json` 和 `reports/free-source-latest.json`。本次附带的联赛聚合清单包含额外温网历史扫描，普通扫描默认只抽查各类别最近 20 个历史事件。审计脚本没有接入线上调度，也不代表新增类别已经有可用预测模型。
