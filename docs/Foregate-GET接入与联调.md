# Foregate 网球 GET 接入与联调

本实现沿用旧 Demo 的 `getAI → aiExtract → openAI` 流程。普通预测请求不访问外部网络，不使用 Poly 价格作模型输入。

## 本地体验

先下载成功的 Actions 模型制品并解压到项目根目录，或执行 `python refresh.py`。

```bash
python3 server.py --demo --port 8105
```

打开 `http://127.0.0.1:8105/demo`。支持 ATP/WTA 切换、11 种玩法、全场／首盘／第二盘大小局的盘口切换、三语、可拖动 AI 悬浮球、模型依据、关闭与重试。概率来自本地模型；所有对阵明确标记为合成测试，不代表实际赛程。`--demo` 只允许绑定本机地址，普通服务不会提供合成赛程或 Demo 页面。

## 正式请求：只需要两名球员

```bash
curl -G 'https://gateway.watchlived.cc/predict' --data-urlencode 'type=tennis' --data-urlencode 'tour=wta' --data-urlencode 'a=Qinwen Zheng' --data-urlencode 'b=Aryna Sabalenka' --data-urlencode 'lang=zh'
```

`a`／`b` 使用球员完整唯一姓名或内部 ID。`tour=atp/wta` 用来选择球员池，不需要具体联赛或赛事名；双方在同一球员池唯一可识别时可以省略。`lang=zh/en/vi` 默认为 `zh`。`categoryId` 可用索引登记的 ATP/WTA 分类，ATP 已知值为 `30157`；不猜测 WTA 分类 ID。`tour` 与已登记的 `categoryId` 不一致时拒绝。

姓名忽略大小写、空格及常见标点，包括 `-`、`_`、点号、引号；兼容 Unicode 重音与全角拉丁字母。例如 ` QINWEN--ZHENG `、`Qinwen_Zheng` 与 `Qinwen Zheng` 匹配同一球员；内部 ID `s0ag` 与 `S0AG` 一致。标准化后仍须唯一，无法自动翻译中文名、猜测拼错的姓名、同姓或不明确的缩写；已人工核实的别名由 `config/player-aliases.json` 维护。`type/tour/lang/mode` 等控制值兼容大小写和首尾空格。参数名本身保持文档写法。

`eventSlug`、`marketId` 都可选。调用模式：

| `mode` | 行为 |
| --- | --- |
| `auto`（默认） | 没有 slug 或 slug 未收录时按球员预测；有已收录赛事则使用其已审核背景及实际盘口 |
| `players` | 明确进行假设对阵预测；即使传了 slug，也不绑定真实赛事／选项 |
| `fixture` | 严格要求已审核赛事；没有 slug 或未收录时返回不可用 |

已收录赛事仍检查双方身份、时间、分类和背景，信息矛盾、已开赛或资料过期时明确返回不可用，不静默改成一场假设比赛。调用者确实只想比较球员时可显式用 `mode=players`。

## 缺少比赛背景时的处理

球员基础预测返回 `prediction_mode=player_baseline`、`fixture_matched=false`、`context_verified=false`。不需要前端查场地或传比赛日期。未提供的信息通过 `assumptions` 明示：

- 盘制默认 `best_of=3`（三盘两胜）、决胜盘抢七目标分 `final_tiebreak_points=7`、`indoor=false`。ATP 五盘比赛应传 `best_of=5`，决胜盘抢十应传 `final_tiebreak_points=10`；缺省值不是对真实比赛规则的核实。
- 未提供场地时，分别计算 Hard、Clay、Grass，再按双方历史各场地场次加一的共同权重汇总。`surface_scenarios` 返回权重；它们是建模权重，不是对真实赛事场地的概率判断。可传 `surface=Hard/Clay/Grass/Carpet` 计算指定场景。
- 默认使用主巡回赛标准单打模型。已有球员的假设对阵可以计算，不代表 Challenger、资格赛、ITF、双打等实际赛事已获得对应训练和验证。
- 可选 `date`、`rank_a`、`rank_b`；错误日期、无效排名或不支持的赛制会返回不可用，不回退成只有整体完赛率的“成功预测”。

基础路径复用原胜负和比分模型，但缺省背景汇总尚无独立回测。因此返回 `market_validation=null`、`validation_protocol=player_scenarios_not_independently_backtested`，不把原有已知场地模型的测试准确率套用到该结果。完赛率仍明确为历史总体基线。

## 前端传值与具体盘口

沿用旧 Demo 的 GET 整场预测、缓存、按玩法提取概率及 AI 浮层，不需要额外查询具体联赛：

```javascript
const tour = detail.categoryPaths?.some(x => /\/WTA$/i.test(x)) ? 'wta'
  : detail.categoryPaths?.some(x => /\/ATP$/i.test(x)) ? 'atp' : null;
const query = new URLSearchParams({
  type: 'tennis',
  a: detail.matches.homeTeam.name,
  b: detail.matches.awayTeam.name,
  lang: 'zh',
});
if (tour) query.set('tour', tour);
if (detail.eventSlug) query.set('eventSlug', detail.eventSlug);
if (detail.marketId) query.set('marketId', String(detail.marketId));
const response = await fetch(`https://gateway.watchlived.cc/predict?${query}`);
if (!response.ok) throw new Error(`Prediction HTTP ${response.status}`);
const result = await response.json();
```

不要把球员名拼接到 URL；使用 `URLSearchParams`，避免空格、`+`、`&` 等被当作查询语法。球员顺序沿用 detail 的 homeTeam / awayTeam。

默认三盘返回 11 类玩法的 35 个常用参考盘口。已审核赛事优先计算已导入的实际盘口。前端可传 URL 编码的 `markets` JSON 数组，精确指定当前页面盘口；上限 200 项、URL 上限 32,000 字符：

```json
[
  {"market_type":"moneyline"},
  {"market_type":"tennis_match_totals","line":22.5},
  {"market_type":"tennis_set_games_totals","set_number":2,"line":9.5}
]
```

参考盘口标为 `market_specs_origin=reference_grid`，自定义为 `query`；不能把参考线当作当前已挂牌盘口。球员基础路径不返回 `foregate_outcomes`／`poly_outcomes` 真实选项绑定，即使传入了 marketId 或单项 id。前端必须依据玩法类型、线、盘号、让分方向和实际选项语义进行匹配，不凭数组位置贴概率；资料不足的盘口显示不可用。

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

生产服务器每 15 分钟刷新索引；GitHub 日更独立刷新历史模型和完赛基线，发布校验过的模型包。严格赛事路径缺少或过期背景时返回不可用；球员基础预测独立可用。部署及回滚方式见 [生产部署](生产部署.md)。

## 响应与前端使用

- `ready` 只表示本次有可计算的研究结果，不代表生产结算已验证；始终保留 `contract_ready=false`。
- `platform_markets.moneyline` 提供 `home`／`away`；其余玩法按原 `sportsMarketType` 提供多条结果。`market_results` 提供同样结果的平铺数组。
- 每条结果有参数唯一 `key`、`line`、`set_number`、`handicap_selection`、`score`、`pairs` 和质量字段；前端必须精确匹配这些参数。
- `reasons[key]` 是当前参数的依据，含真实历史评级、对应路径的验证说明及历史频率基线（如有）。同一玩法类型的泛用依据可用 `reasons[type]`。
- 对由 Foregate detail 导入的实际盘口，`foregate_outcomes` 按原选项顺序返回 ID、标题及概率。调用方自定义 `markets` 时不会继承原盘口的 ID 绑定，防止换线后串配。
- 对从 Gamma 导入的实际盘口，返回 `polyMarketId` 和按原始顺序排列的 `poly_outcomes`（`assetId`、`title`、`probability`）。前端可按 detail 既有的 `yesAssetId`／`noAssetId` 精确对应，不能将 Gamma market ID 当作 Foregate outcome ID。
- 指定盘的 `pairs` 保留未进行到该盘的概率质量，和可能小于 1；`period_not_reached_probability` 单列。不得把它默认为输，也不得静默归一化。
- 未完赛和是否完赛是历史整体基线，不是个体伤病风险。正常比分预测仍条件于正常完赛；尚未完整适配所有 Poly 退赛／取消结算。
- `unavailable` 提供赛事或玩法缺失原因。前端复用旧版“暂不支持该项结果预测”。HTTP 参数语法错误为 400；业务范围不可用返回 200、`ready=false` 和原因。
- 浏览器缓存按完整请求区分，切换赛事、语言、盘口、盘号或球员方向后重新匹配。缓存键应包含完整规范化请求和模式；Demo 缓存至多 60 秒，已审核赛事过开赛时间不用缓存。球员基础预测不代表实时比赛。

## 统一网关

网关增加显式启用的网球注册。默认仍运行原四个引擎，设置以下变量后新增 `type=tennis`，监听内部 8105 端口：

```bash
FG_TENNIS_DIR=/absolute/path/FG-tennis-prediction \
FG_TENNIS_MODEL=/absolute/path/FG-tennis-prediction/models/current.json \
FG_TENNIS_FIXTURES=/absolute/path/foregate-fixtures.json \
python3 gateway.py
```

可选 `FG_TENNIS_EXPANDED_MODEL` 加载扩展快照。网关保留原域名、GET 和跨域，去掉 `type` 后对网球 `/predict` 注入 `view=foregate`。原引擎路由保持原样。网球路径部署在 `/opt/fg-tennis-current`。生产已独立部署，代码与模型分别管理；免费模型由 GitHub 日更、VPS 校验同步，赛程由 VPS 采集。详见 [生产部署](生产部署.md)。旧的无 type/view 且显式传 surface 的本地 `/predict` 继续返回原始胜负结构；统一网关始终注入 view=foregate，因此前端统一使用 platform_markets 结构。
