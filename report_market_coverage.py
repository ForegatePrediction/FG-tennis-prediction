#!/usr/bin/env python3
"""Publish the observed 38-family capability matrix and actual validation."""
import json
from core.coverage import coverage
from core.data import ROOT,atomic_json


def build():
    matrix=coverage();atomic_json(ROOT/'reports/market-model-coverage.json',matrix)
    reports={t:json.loads((ROOT/f'reports/{t}-counts-backtest.json').read_text()) for t in ('atp','wta')}
    lines=['# 网球全部玩法预测覆盖与新增模型验证 — 2026-10-26','',
           '**结论：目前不能可靠覆盖 Poly 网球所有玩法。** 已将 38 个研究类别逐项映射到模型能力：11 类比赛玩法有正常完赛条件下的实验性计算，9 类有依赖完整签表的实验性推演，1 类有历史完赛基线，17 类仍无可用模型。现有经过原始回测的单打胜负模型保留原行为。', '',
           '不能把 21/38 理解为生产覆盖率：部分能力仅在单打签表、完赛等条件下成立；Not Completed 现可用整体历史基线估计，国籍夺冠仅覆盖一张签表，其他玩法仍有退赛／弃权口径问题。签表不是自动获取，默认球员范围为成人 ATP/WTA 主巡回赛单打。本轮没有部署到 VPS，也未推送新 GitHub 仓库。','',
           '最新改进与完整结果见 [大小分、完赛与扩展玩法 V2](大小分、完赛与扩展玩法-v2-2026-10-26.md)。','',
           '后续已完成截图盘口批量计算、原生 outcome／Token 映射，以及独立 ATP Challenger 正赛／ATP 资格赛扩展模型。详见 [截图盘口实现与实际覆盖](截图盘口实现与实际覆盖-2026-10-26.md)。下表保留默认主巡回赛模型的测试结果；扩展模型另行报告，Challenger 资格赛仍缺验证数据。','',
           '## 已完成的代码与模型','',
           '- `core/scoring.py`：发球分→局→盘→全场概率递推；第一发球方以 50/50 混合，决胜盘抢七目标显式提供。',
           '- 新增 core/counts.py：直接学习正常完赛的总盘数及条件盘比分，按终局比分重新加权所有路径，保留原胜负模型概率，并使总局数、总盘数、盘内局数和让分来自同一个分布。',
           '- `train_counts.py`：2012—2022 拟合、2023 选择并重新拟合、2024 温度校准，复用 2025 年以后测试期做回顾比较。旧 backtest_score.py 保留用于对照。严格使用赛前历史；需要后续前向验证。',
           '- `core/tournament.py`：完整单淘汰签表的精确概率传播，支持轮空、晋级、决赛组合、资格赛／外卡集合事件、种子首轮出局及单签表冠军国籍分布。',
           '- `GET /predict/market`、`POST /predict/tournament`、`GET /coverage` 已接入本地 HTTP 服务；原 `/predict` 返回保持兼容。','',
           '## 独立测试的实际结果','',
           '模型历史截至 2026-10-24；ATP 4,748 场、WTA 4,541 场，共 9,289 场。仅正常完成、标准单打。本轮新增比分模型整体仍为 experimental；签表推演只验证数学与接口正确性，尚未做完整真实赛事的夺冠／晋级回测。','',
           'Log loss 越低越好。基线为 2024 年同盘制／同参数的平滑历史频率，作为低门槛比较，不是赔率模型。以下大小分结果混合三盘／五盘测试场次，完整参数样本和校准分箱见 JSON。','',
           '| 玩法／参数 | ATP 模型 | ATP 基线 | WTA 模型 | WTA 基线 |',
           '| --- | ---: | ---: | ---: | ---: |']
    for key,label in [('moneyline','单场胜负'),('tennis_first_set_winner','第一盘胜者'),
                      ('tennis_set_winner:{"set_number": 2}','第二盘胜者'),
                      ('tennis_game_handicap:{"line": -3.5}','A 让 3.5 局'),
                      ('tennis_match_totals:{"line": 22.5}','全场总局数 22.5'),
                      ('tennis_set_totals:{"line": 2.5}','全场总盘数 2.5')]:
        values=[reports[t]['markets'][key][group]['log_loss'] for t in ('atp','wta') for group in ('model','2024_empirical_baseline')]
        lines.append('| '+label+' | '+' | '.join(f'{v:.5f}' for v in values)+' |')
    lines += ['', '**新版常用总局数 22.5、总盘数 2.5 已改善，但提升幅度不大，不能推广为所有盘口都有效。** API 提供逐参数 market_validation 与 validation_gate：未胜基线、缺少参数测试或仅研究性优于基线都单独标记；全部 contract_ready=false。2025+ 期间已在前轮开发中查看过，属于回顾比较，优于低门槛基线不等于已证明未来有效或盈利。','',
              '同一比赛第三盘／第五盘可能根本没有发生。接口分别给出两边的联合事件概率、period_not_reached_probability 和已到达该盘条件下的概率，不能把未打到当作任一选项输。','',
              '## 全部 38 类能力矩阵','',
              '| 研究类别 | 玩法 | 当前阶段 | 条件／缺口 |', '| --- | --- | --- |']
    names={'experimental_completed_match':'比赛条件预测，实验性','experimental_supplied_draw':'签表条件推演，实验性','historical_base_rate':'历史整体概率基线','unavailable':'尚不可预测'}
    for r in matrix['families']:lines.append(f"| `{r['family']}` | {r['label']} | {names[r['status']]} | {r['reason']} |")
    lines += ['', '## 直接调用示例','',
              '以下是模型演示的假设对阵，不表示 Poly 当前存在对应盘口；surface、盘制、抢七规则、选项及签表必须由经过核实的赛事资料提供。','',
              '```bash','python3 server.py --port 8105',
              "curl 'http://127.0.0.1:8105/predict/market?tour=atp&a=S0AG&b=A0E2&surface=Hard&market_type=tennis_game_handicap&line=-3.5&selection=a&best_of=3&final_tiebreak_points=7&format=main_tour_singles'",'```','',
              '`selection=a&line=-3.5` 表示 A 让 3.5 局；不能直接把 Poly 原始 line 赋给 A。精确比分传 score=2-0，始终按 A-B 顺序。第 N 盘传 set_number=N。大小局／大小盘传 line；整数盘口尚不支持 push 规则，拒绝请求。','',
              '签表接口：POST /predict/tournament，示例 JSON：','', '```json',
              json.dumps({'tour':'atp','surface':'Hard','best_of':3,'format':'main_tour_singles_knockout',
                          'draw_verified':True,'source':'假设对阵演示，非真实赛程',
                          'draw':[{'id':'S0AG','seed':1,'entry':'DA','country':'ITA'},
                                  {'id':'A0E2','seed':2,'entry':'DA','country':'ESP'}]},ensure_ascii=False,indent=2),'```','',
              '数组按实际签表相邻位置排列；允许 None/null 轮空，2～128 个槽位且为 2 的幂；不得重复球员／种子，明确 entry=DA/Q/LL/WC/unknown。draw_verified 表示调用方核实，服务本身不核验来源。当前模型不把循环赛、团体对阵、双打组合转换为单打签表。','',
              '## 免费数据能做什么，仍缺什么','',
              '本轮直接复用已下载的 TennisMyLife 免费主巡回赛 CSV，无新增 API Key、付费 API 或赔率依赖。赛果、盘比分、发球分／接发球分统计足以建立本轮比分模型；但不是每场都有统计，缺失时向总体先验收缩，API 返回样本证据。','',
              '已利用该源公开的 Challenger 正赛及 ATP 资格赛文件构建独立扩展实验模型，保存在 models/expanded/，不改变这里的默认主模型。Challenger 资格赛仍缺少验证数据。WTA 资料的来源可靠性和原始日期粒度限制延续原报告。ITF、双打和青少年仍需完整、可更新并经许可核查的数据源，不能以分类已发现替代球员可预测。','',
              '完赛概率已改用 Poly 明确结算的 Completed Match 合约标签，纳入取消等 No；保留规则版本、标签时间及 17 天成熟窗口。原始 CSV 的 RET/W/O 不能直接替代全部完赛合约。模型是整体历史基线，不是个人伤病概率。','',
              '签表、报名、伤病、赛历、积分规则、裁判事件、公告与品牌活动分别需要额外输入。目前没有一个经核实的免费接口能保证本项目覆盖所有这些标签和 Poly 事件，因此未伪造长尾概率。','',
              '## 接下来提高可用覆盖率的顺序','',
              '1. 优先修正比分分布对总局数／总盘数的校准：研究由原胜率反推发球强度、比赛间状态混合和场地效应；只用新的验证设计选择，保留后续前向测试。',
              '2. 增加完赛／退赛风险模型与逐版本结算适配，才能补齐 Completed Match、精确比分未完成分支和合约无条件概率。',
              '3. 打通免费、可核验的完整签表与参赛状态，并对真实赛事夺冠／晋级作历史回测；自动同步目前尚未实现。',
              '4. 在已完成 Challenger 正赛／ATP 资格赛扩展的基础上补齐 Challenger 资格赛，再验证 ITF、双打和青少年数据，按实际 Poly 事件与球员映射统计覆盖率。',
              '5. 循环总决赛、赛季积分／冠军数量等另建模型。行为、纪律、新闻及周边类别不通过现有竞技模型直接生成概率。','',
              '## 工程验证与产物','',
              '新增概率质量守恒、交换对称、盘序与发球衔接、比分联合分布、未打到盘、让分方向、非法规则拒绝、签表轮空／重复／路径互斥、模型快照哈希与 HTTP GET/POST 的验证。单元测试只能验证实现，不能代替预测准确性回测。','',
              '- `models/score-config.json`：与原胜负快照 SHA256 绑定的实验比分配置及逐参数验证。',
              '- `reports/atp-score-backtest.json`、`reports/wta-score-backtest.json`：完整回测与历史频率基线。',
              '- `reports/market-model-coverage.json`：全部 38 类可供前端读取的能力矩阵。',
              '- 日更脚本增加比分配置重建；GitHub 制品包含比分配置。胜负快照与比分配置哈希不匹配时拒绝比分预测，刷新后需重启本地服务。此配置仍未在新仓库或 VPS 上启用。','',
              '## 方法依据与资料','',
              '- [Newton & Aslam, Monte Carlo Tennis](https://epubs.siam.org/doi/10.1137/050640278)：从发球分概率计算局／盘／比赛与淘汰赛概率的研究依据；本项目采用确定性递推，自行实现。',
              '- [Gollub, Forecasting serve performance in professional tennis matches](https://journals.sagepub.com/doi/10.3233/JSA-200345)：讨论有限样本和对手强度造成的发球估计偏差，是本轮限制与后续方向的依据。',
              '- [TennisMyLife 数据页面](https://stats.tennismylife.org/tennis-match-database)：免费年度赛果、统计与挑战赛／资格赛入口；免费可下载不代表所有使用权已由本项目独立核实。',
              '- [Poly 全部玩法目录](Poly网球全部玩法类型-2026-10-26.md)。','']
    path=ROOT/'docs/网球全部玩法预测覆盖与模型验证-2026-10-26.md'
    path.write_text('\n'.join(lines));print(path)
    return matrix


if __name__=='__main__':build()
