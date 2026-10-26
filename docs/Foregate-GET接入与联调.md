# Foregate 网球 GET 接入与联调

本实现沿用旧 Demo 的 `getAI → aiExtract → openAI` 流程。普通预测请求不访问外部网络，不使用 Poly 价格作模型输入。

## 本地体验

先下载成功的 Actions 模型制品并解压到项目根目录，或执行 `python refresh.py`。

```bash
python3 server.py --demo --port 8105
```

打开 `http://127.0.0.1:8105/demo`。支持 ATP/WTA 切换、11 种玩法、全场／首盘／第二盘大小局的盘口切换、三语、可拖动 AI 悬浮球、模型依据、关闭与重试。概率来自本地模型；所有对阵明确标记为合成测试，不代表实际赛程。`--demo` 只允许绑定本机地址，普通服务不会提供合成赛程或 Demo 页面。

## 正式请求形状

```text
GET /predict?type=tennis&tour=atp&a=完整姓名A&b=完整姓名B&eventSlug=已导入赛事slug&lang=zh
```

`tour` 使用 `atp`／`wta`，也可使用索引里核实的 `categoryId` 映射；两者同时传时必须一致。`a`／`b` 使用球员完整唯一姓名或内部 ID。`lang` 为 `zh`／`en`／`vi`。可透传 Foregate 字符串 `marketId` 关联页面。

优先计算已导入赛事的实际盘口。若索引只包含比赛背景，则返回注明 `market_specs_origin=reference_grid` 的常用参考盘口，不能将这些参考盘口误当作 Foregate 当前挂牌盘口。也可传 URL 编码的 `markets` JSON 数组，列出页面的具体盘口；上限 200 项、URL 上限 32,000 字符。

```json
[
  {"market_type":"moneyline"},
  {"market_type":"tennis_match_totals","line":22.5},
  {"market_type":"tennis_set_games_totals","set_number":2,"line":9.5}
]
```

服务会检查赛事身份、ATP/WTA、双方球员、开赛时间及背景来源。赛事资料必须在 48 小时内检查过，且比赛尚未开始、在未来 14 天以内。请求不能覆盖索引里的场地、盘制或赛事层级。

## 本地赛事索引

`import_foregate_fixtures.py` 接受 Foregate detail 或 Gamma 事件，以及独立核实的比赛背景：

```bash
python3 import_foregate_fixtures.py \
  --events /path/to/foregate-details.json \
  --contexts /path/to/reviewed-contexts.json \
  --output data/foregate-fixtures.json
python3 server.py --fixtures data/foregate-fixtures.json
```

`--events` 可为一个对象或多个对象组成的数组；背景文件模板见 `examples/fixture-contexts.example.json`。每条背景包含：同一赛事 slug、完整有序球员姓名、`tour`、`verified=true`、来源、真实核查时间，以及 `surface`、`best_of`、`final_tiebreak_points`、`indoor`、`competition`、`format`。必须核实后填写；模板中未核实的空值不能直接投入运行。

主巡回赛使用 `competition=main_tour`、`format=main_tour_singles`。Challenger 正赛／ATP 资格赛分别用 `challenger_main_draw`／`atp_qualifying` 和 `expanded_atp_singles`，并显式加载独立扩展快照：

```bash
python3 server.py --fixtures data/foregate-fixtures.json \
  --expanded-model models/expanded/current.json
```

导入器保留 Foregate `outcomeId`、`optionId`、`assetId` 字符串以及 Yes／No 的真实选项顺序；兼容 `sportsMarketType`／`marketSportsType`，冲突时拒绝。使用实际 `matchStartTime`，不用市场创建时间。已有资格赛证据时，禁止导入为正赛。盘口无法明确解析时保留逐项不可用原因，不猜测盘号、让分方向或缺失的盘口线。

多个玩法必须提供各自规则，不能把整场 moneyline 的规则复制给大小局等玩法。单一玩法的 detail 可使用外层 `rules`。精确比分自动映射支持明确 A-B `score` 或“具名球员 win 2-0”等明确语义，以及 Not Completed；无法识别方向的裸比分和 Other 仍返回不可用。

导入有赛事级错误时不会覆盖现有索引；成功后原子替换文件，HTTP 请求自动读取新索引，无需重启。更换模型快照仍需重启服务。

生产采集器 `refresh_fixtures.py` 分页获取免费 Gamma 开放网球事件，仅导入 `config/competitions-reviewed.json` 中按日期、赛事名和 ATP/WTA 精确核实的正赛单打。首批登记为 2026-10-26 至 11-01 的 Basel、Vienna、Tokyo；依据是 ATP 官方赛历、WTA 官方东京赛事页及标准单打规则。资格赛、双打、未知赛事和已开始比赛不会因此获得默认背景。登记需要随赛历继续补充，不能宣称完整覆盖 Poly。

生产服务器每 15 分钟刷新索引；GitHub 日更独立刷新历史模型和完赛基线，发布校验过的模型包。缺少或过期背景时仍返回不可用。部署及回滚方式见 [生产部署](生产部署.md)。

## 响应与前端使用

- `ready` 只表示本次有可计算的研究结果，不代表生产结算已验证；始终保留 `contract_ready=false`。
- `platform_markets.moneyline` 提供 `home`／`away`；其余玩法按原 `sportsMarketType` 提供多条结果。`market_results` 提供同样结果的平铺数组。
- 每条结果有参数唯一 `key`、`line`、`set_number`、`handicap_selection`、`score`、`pairs` 和质量字段；前端必须精确匹配这些参数。
- `reasons[key]` 是当前参数的依据，含真实历史评级、匹配参数的回顾性回测及历史频率基线（如有）。同一玩法类型的泛用依据可用 `reasons[type]`。
- 对由 Foregate detail 导入的实际盘口，`foregate_outcomes` 按原选项顺序返回 ID、标题及概率。调用方自定义 `markets` 时不会继承原盘口的 ID 绑定，防止换线后串配。
- 对从 Gamma 导入的实际盘口，返回 `polyMarketId` 和按原始顺序排列的 `poly_outcomes`（`assetId`、`title`、`probability`）。前端可按 detail 既有的 `yesAssetId`／`noAssetId` 精确对应，不能将 Gamma market ID 当作 Foregate outcome ID。
- 指定盘的 `pairs` 保留未进行到该盘的概率质量，和可能小于 1；`period_not_reached_probability` 单列。不得把它默认为输，也不得静默归一化。
- 未完赛和是否完赛是历史整体基线，不是个体伤病风险。正常比分预测仍条件于正常完赛；尚未完整适配所有 Poly 退赛／取消结算。
- `unavailable` 提供赛事或玩法缺失原因。前端复用旧版“暂不支持该项结果预测”。HTTP 参数语法错误为 400；业务范围不可用返回 200、`ready=false` 和原因。
- 浏览器缓存按完整请求区分，切换赛事、语言、盘口、盘号或球员方向后重新匹配。Demo 缓存至多 60 秒，过开赛时间不用缓存。

## 统一网关

网关增加显式启用的网球注册。默认仍运行原四个引擎，设置以下变量后新增 `type=tennis`，监听内部 8105 端口：

```bash
FG_TENNIS_DIR=/absolute/path/FG-tennis-prediction \
FG_TENNIS_MODEL=/absolute/path/FG-tennis-prediction/models/current.json \
FG_TENNIS_FIXTURES=/absolute/path/foregate-fixtures.json \
python3 gateway.py
```

可选 `FG_TENNIS_EXPANDED_MODEL` 加载扩展快照。网关保留原域名、GET 和跨域，去掉 `type` 后对网球 `/predict` 注入 `view=foregate`。原引擎路由保持原样。网球路径必须部署在持久位置；当前未把它加入既有四引擎的 VPS 双通道发布流程，也未自动部署 VPS。
