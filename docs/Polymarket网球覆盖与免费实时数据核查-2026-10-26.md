# Polymarket 网球覆盖与免费更新数据核查

核查时间：北京时间 2026-10-25 深夜至 10-26 凌晨。Poly 开放事件扫描完成于 UTC 2026-10-25 15:57；免费文件和 ESPN 检查约为 UTC 16:03。以下是冻结快照，数字会随市场创建、关闭而变化。

## 结论

免费 CSV 可以继续作为训练历史和日更对账来源；应配合免费公开接口获取赛程、比赛状态和精确时间。不能从文件扩展名推断更新慢，也不能从接口响应快推断数据完整或赛果实时。

现有交付只经过 ATP/WTA 主巡回赛单打验证，**尚未覆盖 Poly 全部网球赛事**。本次已完成真实接口调用、公开实时通道探测，以及可重复运行的覆盖审计代码；没有将未训练的 ITF、双打、青少年模型上线，也没有启动新的线上定时任务。

## 1. CSV 更新速度的实际证据

从 [TennisMyLife 官方索引](https://stats.tennismylife.org/api/data-files) 读取文件修改时间，并实际下载七个文件，校验列、行数、赛事和轮次。发布者[数据库页面](https://stats.tennismylife.org/tennis-match-database)说明有在赛更新，但没有可核验的逐场更新时限承诺。

| 文件 | 发布者修改时间（UTC，10 月） | 检查时文件年龄 | 实际行数 |
| --- | --- | ---: | ---: |
| `2026_challenger.csv` | 2026-10-19T04:34:46.568Z | 155.47 小时 | 6,447 |
| `2026_wta.csv` | 2026-10-25T13:01:00.733Z | 3.03 小时 | 2,375 |
| `2026.csv` | 2026-10-25T13:01:00.727Z | 3.03 小时 | 2,575 |
| `atp_quali/2026_atp_quali.csv` | 2026-10-24T23:58:27.071Z | 16.07 小时 | 1,241 |
| `challenger_ongoing_tourneys.csv` | 2026-10-25T12:06:29.344Z | 3.94 小时 | 153 |
| `ongoing_tourneys.csv` | 2026-10-25T12:10:09.710Z | 3.88 小时 | 80 |
| `wta_ongoing_tourneys.csv` | 2026-10-25T13:00:06.619Z | 3.05 小时 | 58 |

这说明主巡回赛和在赛 CSV 当天确有更新，挑战赛年度文件则可能按周归档，必须同时读取在赛文件。**文件年龄不是赛果延迟**；一次检查不能证明每场比赛在结束后几分钟入库。`tourney_date` 官方定义是赛事周，不能统一当作比赛发生时间。

下载文件已包含 Almaty、Lyon、宁波、大阪决赛胜者，ESPN 查询也返回同样胜者。其中存在时间顺序疑点：ATP 在赛文件索引修改时间为 12:10 UTC，但其中 Lyon 决赛在 ESPN 的 `date/startDate` 是当天 13:35 UTC。因此两端时间字段尚未充分一致，不能依据这些时间声称“结束后 X 分钟更新”。原始证据在 `reports/poly-espn-comparison.json`，需进一步核验真实开赛/结束时间和发布者 mtime 含义。

上一版模型普通赛事等待 7 天、大赛等待 14–15 天，是为防止赛事周日期造成回测泄漏而设的保守窗口，**不是源 CSV 固有延迟**。只有核实精确比赛时间及当时可见时间之后，才可逐场更新 Elo、近期状态和交锋；不能为了实时性直接删除保护窗口。

## 2. 免费接口是否更好

| 来源 | 本次核实 | 可承担的工作 | 实际边界 |
| --- | --- | --- | --- |
| TennisMyLife CSV | 七个文件真实下载成功，无 Key | 多年历史、排名/发接发统计、主巡回赛日更；扩展挑战赛单打和 ATP 资格赛 | 不是覆盖全部 ITF/双打/青少年的数据库；WTA 可靠性仍需交叉核对 |
| ESPN 公开 scoreboard | ATP/WTA 均 HTTP 200，无 Key | 主巡回赛赛程、资格赛、单双打状态与逐盘赛果；部分较低级别女赛也有记录 | 没有确认完整 ITF/挑战赛覆盖；没有稳定性和延迟 SLA |
| Poly Gamma | 真实分页读取，无 Key | 以市场为准发现目标对阵、赛事分类、市场类型及结算规则 | 分类元数据响应可能缓存 20–30 分钟；不适合作为实时比分接口 |
| Poly Sports WebSocket | 30 秒连接成功，收到 24 条消息，其中 2 条网球消息 | 本平台公开实时比赛状态/比分，适合与 Poly 对齐 | 本次仅观察到 ATP；不能证明所有 ITF/双打均有推送；实测网球帧没有 `last_update`，无法量化延迟 |
| LiveTennisAPI 免费套餐 | 仅核实官方文档，未申请 Key、未调用 | 文档列出 ATP/WTA/Challenger/ITF/青少年实时及赛程 | 每天 100 请求；历史与 WebSocket 主要在付费层，不能当成永久免费完整历史库 |
| Tennis API / Matchstat 免费套餐 | 仅核实官方文档，未申请 Key、未调用 | 文档列出多级别 fixtures/results/live | 每天 50 请求；未实测具体覆盖，不适合高频全量轮询 |

ESPN 本轮响应 `Cache-Control` 为 ATP `max-age=9`、WTA `max-age=3`，较早一轮为 2 秒和 1 秒；这只是缓存寿命，**不是球场到接口的实测延迟**。查询某一天可能返回整个赛事签表，必须再按单场 `competition.date` 筛选，不能把所有返回记录当作当天比赛。

在严格“完整双方姓名 + 同一 UTC 比赛日期 + 唯一匹配”规则下，本次 ESPN 快照与 Poly 未关闭单打事件匹配 23 场（ATP 3、WTA 20）。未匹配不等于数据必然不存在，可能涉及排期变更、姓名差异和查询窗口；双打尚未做可靠选手 ID 对齐。因此不能凭两次 HTTP 200 宣称 ESPN 覆盖全部 Poly。

[Poly Sports 官方文档](https://docs.polymarket.com/api-reference/wss/sports)、[LiveTennisAPI 免费额度与历史限制](https://docs.livetennisapi.com/reference.html)、[Tennis API 免费额度](https://docs.tennis-api.com/getting-started)。100 请求/天若按每 30 秒一轮，50 分钟即用完；即使一个请求能返回全场列表，分页、详情等也会消耗额外额度。

另有 LiveTennisAPI 的[学术历史数据计划](https://livetennisapi.com/data/academic)，覆盖 ITF/双打等，但免费资格限非商业学术研究、完整数据须申请，不能直接据此认定 ForeGate 已有完整免费的生产训练数据。

## 3. Poly 实际覆盖什么

调用 `/sports`，并用 `/tags/slug/tennis` 确认 tennis tag 是 **864**；只按这个精确 tag 归类，排除乒乓球。官方元数据存在以下八个分类：

| sport | 名称 | series_id | 证据 |
| --- | --- | --- | --- |
| atp | ATP Tour | 10365 | 当前对阵；实际也含挑战赛和资格赛 |
| wta | WTA Tour | 10366 | 当前对阵 |
| itf | ITF | 11634 | 当前男女低级别赛事、资格赛 |
| atp-doubles | ATP Doubles | 11632 | 当前对阵；含挑战赛双打 |
| wta-doubles | WTA Doubles | 11633 | 当前对阵 |
| wimbledon | Wimbledon | 12012 | 历史 801 个已关闭事件，分页到末页；包括成人、资格赛、青少年单双打 |
| daviscup | Davis Cup | 12826 | 本次抽查 20 个历史事件，包括单打、双打 |
| bjkcup | Billie Jean King Cup | 12827 | 有官方分类，但本次该 series 的全部状态查询为空；不能说已验证有实际对阵 |

`ATP Tour` 是 Poly 分类名，**不能等同 ATP 主巡回赛级别**。例如 Guayaquil、Brest、Seoul、Sioux Falls 等被放在 ATP 类别；`eventMetadata.tennisFixtureSource` 对部分对阵明确标记 `optic-challenger-qualifying`。温网青少年也沿用 ATP/WTA/双打 sport，但归在 Wimbledon series。ATP 单双打还共享 primaryTag，所以必须同时使用 sport、series、格式、赛事和轮次做映射。

本次全量遍历 `active=true&closed=false&tag_id=864`，每页 100 条，直至末页，共 **638 个未关闭事件**。其中可能含旧市场及长周期合约，**不是今天的比赛数量**。只统计有双方对阵标题、moneyline 且其市场 active、未关闭、acceptingOrders 的事件，共 **606 场**；接口标志不保证实际流动性。细分如下：

| Poly 分类 | 未关闭事件 | 有可接受订单的单场胜负市场事件 |
| --- | ---: | ---: |
| ITF | 413 | 394 |
| ATP 分类 | 121 | 119 |
| WTA 分类 | 23 | 23 |
| ATP 双打 | 54 | 54 |
| WTA 双打 | 16 | 16 |
| 冠军、排名、退役等其他合约 | 11 | 0 |

开放事件中识别到 399 个 ITF 资格赛、38 个 ATP 类别资格赛、2 个 ATP 双打资格赛。识别使用赛事介绍与元数据，排除结算规则里的 `disqualification`，避免把所有正赛误判为资格赛。

另外抽查最近 1,000 个已关闭网球事件、各分类历史样本和温网 801 个已关闭事件，去重后总计 **2,467 个事件**。这些有界样本不能证明平台所有历史赛事已穷尽。当前 ITF 名称涉及 M15、M25、W15、W35、W50、W75、W100；历史温网样本包含青少年单打和双打，未在本次温网样本中发现混双或轮椅。不存在证据的项目不擅自写成已覆盖。

当前全部赛事名称见文末；完整逐场记录见 `reports/poly-coverage-latest.json`，按 sport/league 聚合清单见 `reports/poly-league-inventory.json`。

## 4. 与现有模型的差距

| 范围 | 免费数据情况 | 现有成品状态与补齐工作 |
| --- | --- | --- |
| ATP/WTA 主巡回赛成人单打、成人大满贯单打 | 已有长期 CSV，ESPN 可辅助更新 | 已有离线验证的模型；还需生产赛程接入、精确时间与 Poly 结算口径适配 |
| ATP 挑战赛单打正赛 | 已下载核实 2026 年度 6,447 行、在赛 153 行；索引有多年历史 | 可以扩展训练；当前成品尚未使用这些记录，旧准确率不能套用 |
| ATP 主巡回赛资格赛 | 已下载核实 2026 年 1,241 行，含 Q1/Q2/Q3 | 可以扩展；需与正赛统一球员 ID、分轮次回测 |
| 挑战赛资格赛、WTA 资格赛 | Poly/ESPN 有部分赛程与结果；本次 CSV 不构成完整历史库 | 需补历史、覆盖审计、冷启动与独立验证 |
| ITF 男/女单打及资格赛 | Poly 目录可抓；WS 是否完整推送尚未验证；完整免费历史仍有缺口 | 需补训练数据、低样本分层模型、排名/场地信息和身份对齐 |
| ATP/WTA/挑战赛双打 | Poly 有当前市场；ESPN 主巡回赛有双打签表 | 缺已核实完整免费训练库；需要四名球员和组合特征、独立双打模型 |
| 温网青少年单打/双打 | Poly 有明确历史事件 | 现有成人模型不适用；需青年球员身份、样本和单独验证 |
| Davis Cup / BJK Cup | 前者有单打/双打样本；后者只有分类证据 | 现有模型排除团体赛；需按一场单打/双打建模，不能把国家队团体胜负当单场 |

当前约 66–67% 的回测准确率只对应原 ATP/WTA 成人主巡回赛正常完赛单打样本，不能宣传为上述全部范围的效果。

## 5. “Poly 有的都覆盖”的具体实现口径

目标赛事范围以 Poly 实际市场为准，不用人工固定少数热门联赛白名单。每个新事件进入目录并登记：Poly ID、series、类别、赛事、成人/青少年、单/双打、资格/正赛、准确开赛时间、选手跨源 ID、场地、数据源、模型版本与缺口原因。新增未知分类必须报警/等待映射，不能静默漏掉。

覆盖率至少分别计量：市场发现率、选手 ID 匹配率、赛果入库率、可预测率、及时更新率。优先以去重后的开放单场胜负对阵做分母，保留失配、无源、低样本、不支持模型等事件。**目录全覆盖并不等于可预测率 100%。** 缺资料应明确返回原因，不能靠默认 50% 概率凑覆盖。

建议免费数据组合：CSV 提供历史；Gamma 以 1–5 分钟周期发现市场（实际可见性受服务器缓存制约）；Sports WS 接收实时状态并归档；ESPN 校验主巡回赛赛程/赛果；CSV 每日再对账。新实时数据先带采集时间存储，验证比赛时间、去重与结果一致性后，逐场更新模型。ITF、双打、青少年还要继续寻找或积累可用训练历史，当前不能保证立即做到全部同等质量。

必须适配 Poly 各合约自己的退赛/弃权规则。例如本次 W15 Sharm ElSheikh 单场市场写明：比赛已开始后的退赛/取消资格，晋级者胜；开赛前 walkover 则 50–50；超期未决也可能 50–50。现有模型排除退赛、弃权，仅预测正常完成比赛时的胜者，与这种合约结算目标不同。需要区分正常胜、开赛后退赛、开赛前弃权和作废，才能形成正确的合约概率。

Poly 同时有让盘、让局、总局数、首盘、是否完赛、冠军和排名等市场。当前成品仅单场胜负；实现“赛事覆盖”不能顺带声称支持所有盘口。总局数、让局等必须另建比分/盘局分布模型并单独回测。

## 6. 本次增加与验证

- `audit_polymarket.py`：免费 Gamma 分页、元数据和逐事件库存，原始响应与 URL/采集时间留存。
- `audit_free_sources.py`：公开索引、七类 CSV 与 ESPN 的可重跑核查。
- `capture_poly_sports.mjs`：Node 22+ 内置 WebSocket 的 1–55 秒只读探测，记录实际 schema。
- `tests/test_market_audit.py`：9 项离线测试通过，覆盖精确标签、单/双打、青少年、资格赛误判、开赛时间和可交易标志。
- 原模型训练与预测代码未改动；本轮新增脚本未启用线上调度。

复查命令（进入本目录后执行）：

```bash
python3 audit_polymarket.py
python3 audit_free_sources.py
node capture_poly_sports.mjs 30 reports/poly-sports-probe.json
python3 -m unittest discover -s tests -p test_market_audit.py -v
```

普通 `audit_polymarket.py` 默认抽查各类别 20 个历史事件；本次额外分页取得的温网 801 个历史事件存于 `data/market-audit/2026-10-25/scan/wimbledon-history-*.json`。再次扫描会以当时新结果覆盖 latest 报告，应保留日期目录原始证据。

## 附录：本次开放单场市场的全部赛事名称

以下保留来源英文名称。类别中可能有未及时关闭的旧事件，不是对这些赛事持续更新能力的保证；同一巡回赛不同城市、站点和资格赛先保持独立，以免错误合并。

### atp（14 个来源赛事名称）

Bari；Brest；Cali；Erste Bank Open；Erste Bank Open, Qualification；European Open；Fort Worth；Guayaquil；Ningbo；Seoul；Sioux Falls；St. Tropez；Swiss Indoors Basel；Swiss Indoors Basel, Qualification。

### wta（2 个来源赛事名称）

Guangzhou Open；Pan Pacific Open。

### itf（46 个来源赛事名称）

M15 Burgas；M15 Fayetteville, AR；M15 Fergana；M15 Heraklion；M15 Ithaca；M15 João Pessoa；M15 Maceio；M15 Mazatlan；M15 Monastir；M15 Pembroke；M15 Pontevedra；M15 Selva Gardena；M15 Sharm ElSheikh；M15 Singapore；M15 Yanagawa City；M25 Kigali；M25 Luan；M25 Malta；M25 Mumbai；M25 Sabadell；M25 Sheffield；M25 Slobozia；M25 Tamworth；W100 Wrexham；W15 Campina Grande；W15 Chisinau；W15 Essen；W15 Maanshan；W15 Monastir；W15 Neuquén；W15 Sharm ElSheikh；W15 Singapore；W15 Székesfehérvár；W35 Bakersfield, CA；W35 Kunshan；W35 Malta；W35 Monastir；W35 Santa Margherita di Pula；W35 Sydney；W50 Cherbourg-en-Cotentin；W50 Istanbul；W50 Morelia；W75 Glasgow；W75 Poitiers；W75 Saguenay；W75 Toronto。

### atp-doubles（9 个来源赛事名称）

Brest；Cali；Erste Bank Open；Erste Bank Open, Qualification；Guayaquil；Ningbo；Seoul；Sioux Falls；Swiss Indoors Basel。

### wta-doubles（2 个来源赛事名称）

Guangzhou Open；Pan Pacific Open。
