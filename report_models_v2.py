#!/usr/bin/env python3
"""Write reproducible v2 comparison and deployment status."""
import json
from core.data import ROOT,atomic_json
from core.inference import Engine
from core.coverage import coverage


def main():
    cases=[('ATP 主巡回赛','atp','main_tour',False),('WTA 主巡回赛','wta','main_tour',False),
           ('Challenger 正赛','atp','challenger_main_draw',True),('ATP 资格赛','atp','atp_qualifying',True)]
    comparisons=[]
    for label,tour,competition,expanded in cases:
        prefix=f'{tour}{"-expanded" if expanded else ""}'
        new=json.loads((ROOT/f'reports/{prefix}-counts-backtest.json').read_text())
        old=json.loads((ROOT/f'reports/{prefix}-score-backtest.json').read_text())
        for kind,line in [('tennis_match_totals',22.5),('tennis_set_totals',2.5)]:
            key=kind+':'+json.dumps({'line':line},sort_keys=True)
            x=new['by_competition'][competition][key];older=(old.get('by_competition') or {}).get(competition,old['markets'])[key]
            comparisons.append({'cohort':label,'market_type':kind,'line':line,'n':x['model']['n'],
                                'old_log_loss':older['model']['log_loss'],'new_log_loss':x['model']['log_loss'],
                                'baseline_log_loss':x['2024_empirical_baseline']['log_loss']})
    e=Engine();completion=e.predict_completion();cap=coverage()
    payload={'tour':'atp','a':'S0AG','b':'A0E2','surface':'Hard','best_of':3,'final_tiebreak_points':7,
             'format':'main_tour_singles','competition':'main_tour'}
    sample=e.predict_markets(payload)
    atomic_json(ROOT/'reports/v2-markets-example.json',{'note':'Hypothetical known-player matchup, not an actual scheduled event',**sample})
    data={'comparisons':comparisons,'completion':completion,
          'coverage':{k:cap[k] for k in ('score_families','draw_families','baseline_families','unavailable_families')},
          'hypothetical_screenshot_line_set':sample['summary'],
          'deployment':'local only; not pushed to GitHub or deployed to production',
          'test_caveat':'2025+ reused retrospective comparison; forward validation required'}
    atomic_json(ROOT/'reports/model-v2-summary.json',data)
    lines=['# 大小分、完赛与扩展玩法 V2 — 2026-10-26','',
           '已在本地完成新版大小分模型、整体完赛基线和额外签表玩法。全部使用免费公开历史数据；无需 API Key。尚未推送 GitHub 或部署生产。','',
           '## 大小局、大小盘','',
           '新模型直接学习：在给定最终胜者条件下比赛打几盘，以及给定赛前实力、场地和发球统计时每盘可能出现的比分。对完整比赛路径重新加权，保留原胜负概率；总盘数、总局数、盘内总局数、让局和让盘来自同一分布，避免各自独立校准后互相矛盾。','',
           '训练使用赛前安全可得的 Elo、场地 Elo、排名／积分、经验和发球统计，不把当场结果或 Poly 报价作为输入。2012—2022 拟合、2023 选择／重新拟合、2024 温度校准；未使用 2025+ 标签拟合参数。','',
           '**注意：2025+ 测试期在前轮开发中已查看过，本次属于回顾改进，仍需新的前向验证。** 提升不是收益保证，也不能从几个常用盘口外推到所有盘口。','',
           'Log loss 越低越好。基线为 2024 年同盘制／同参数频率；下列扩展分组还按赛事层级单独统计基线。','',
           '| 范围 | 盘口 | 场次 | 旧模型 | 新模型 | 频率基线 |', '| --- | --- | ---: | ---: | ---: | ---: |']
    for r in comparisons:
        label='总局数 22.5' if r['market_type']=='tennis_match_totals' else '总盘数 2.5'
        lines.append(f"| {r['cohort']} | {label} | {r['n']:,} | {r['old_log_loss']:.5f} | {r['new_log_loss']:.5f} | {r['baseline_log_loss']:.5f} |")
    n=completion['sample']['n'];yes=completion['sample']['yes'];no=completion['sample']['no'];lo,hi=completion['raw_frequency_95pct_wilson']
    lines+=['','完整逐盘口、逐赛事层级结果在 reports/*-counts-backtest.json；API 的 market_validation、validation_cohort 和 validation_gate 标明实际验证范围，未胜基线／无参数样本不会被隐藏。','',
            '## 完赛与否：使用历史整体概率','',
            f'从本地保存的 Poly 全量历史中提取已明确结算的 Completed Match 合约。当前成熟样本 **{n:,}** 条，其中正常完成 **{yes:,}** 条，未正常完成 **{no:,}** 条。整体平滑估计：**正常完赛 {completion["probabilities"][0]:.2%}，未正常完赛 {completion["probabilities"][1]:.2%}**。', '',
            f'记录总体的二项 Wilson 95% 区间约 {lo:.2%}—{hi:.2%}；这不是单场预测的置信保证，也未包含赛事／天气共同冲击和样本选择偏差。','',
            '标签要求 closed=true、UMA 状态 resolved、Yes/No 两项最终值精确为 1/0；不会把尚未结算的高价格当成赛果。正常完赛、弃权、退赛、取消和超时都按原合约实际结算标签计入。当前仅支持核实的 7／14 天规则；保留规则版本、原始来源、结算可用时间和文本哈希。没有独立重放链上结算。','',
            '各训练／验证／测试截止时要求已经结算，并对预定开赛时间加 17 天成熟窗口，避免只纳入快速完赛的 Yes、漏掉仍在等待的取消／延期 No。开赛前已取消的有效 No 也保留。比较分层收缩和全局频率后，验证集选择了全局频率；没有用测试结果换模型。','',
            f'冻结测试 {completion["validation"]["selected"]["n"]:,} 条，Log loss {completion["validation"]["selected"]["log_loss"]:.5f}；并不能把 6% 左右的未正常完赛率理解成选手受伤率。范围为已上市、已成熟且能确认标签的历史市场，不是全部网球赛程。','',
            '新增 GET /predict/completion，可独立于选手历史返回整体概率。Completed Match 已接入批量和 Poly 选项映射；精确比分 Not Completed 使用互补概率。普通精确盘分额外提供 probabilities_including_noncompletion，等于正常完赛基线 × 正常完赛条件下的盘分概率。所有比分选项加 Not Completed 可构成归一化分布。','',
            '## 其他 Poly 玩法','',
            '- 新增 defeat_top_seed：指定球员在任一轮击败排名范围内种子的联合路径概率；不用夺冠概率代替。',
            '- 新增 any_match_win：指定单打球员或球员集合中至少有人赢一场实际比赛；轮空不计作赢球，多个目标不会重复相加。实际双打合约仍不适用。',
            '- 既有夺冠、晋级轮次、决赛组合、资格赛／外卡晋级集合、种子首轮出局及单张签表国籍夺冠，新增统一二元接口 POST /predict/tournament/market，返回 Yes/No。需要完整且调用方已核实的单打淘汰签表。',
            '- 目前 38 个研究类别中：11 类比分计算、9 类签表推演、1 类整体完赛基线，17 类仍缺模型。21/38 是有条件的计算能力数量，不是 Poly 真实赛事覆盖率。',
            '- 仍未用现有竞技模型硬填伤病／参赛、退役公告、禁赛、裁判行为、观众到场、品牌活动、赛季积分和年度冠军数量。它们需要独立免费标签或新模型。','',
            '截图的 BO3 盘口模板现在可返回全部 16 项计算／估计结果；实际截图那场属于 Challenger 资格赛且已过开赛时间，因此仍不回填赛前概率。对尚未开赛的同层级赛事，整体完赛基线可以单独返回，比分仍需对应层级和球员数据通过验证。','',
            '## 接口与复现','',
            '```bash',
            'python3 train_counts.py',
            'python3 train_counts.py --expanded',
            'python3 train_completion.py --as-of 2026-10-24',
            'python3 report_models_v2.py',
            'python3 server.py --port 8105',
            "curl 'http://127.0.0.1:8105/predict/completion?tour=atp&rule_days=14'",'```','',
            '精确比分未完成分支的批量请求项：','',
            '```json','{"market_type":"tennis_exact_score","score":"Not Completed"}','```','',
            '签表二元接口在原 POST /predict/tournament 请求上增加 market_type；指定选手用 player，晋级阶段用 remaining_slots，至少赢一场用 any_win_targets，击败高种子用 top_seed_max，决赛组合用 pair，国籍用 country。','',
            '## 产物、更新与限制','',
            '- models/count-config.json 与 models/expanded/count-config.json：与各自胜负快照哈希绑定的新比分模型。',
            '- models/completion.json 和扩展目录副本：完赛总体基线；不依赖当前选手是否有足够历史。',
            '- data/completion-labels.json：可追溯成熟标签，未加入 Git 跟踪；reports/completion-backtest.json 保存筛选、时间分割和测试。',
            '- refresh.py 已增加新大小分重建，GitHub 工作流制品包含 count-config 和 completion；该工作流仍未启用。完赛基线来自本地历史归档，必须更新 Poly 归档后重新训练；目前没有接通自动日更。健康接口会显示其日期和过期状态。',
            '- 原主胜负快照没有替换。比分的退赛／走盘结算适配未全部完成，统一 contract_ready=false；所有模型只在本地完成验证。','',
            '参考：[Poly 官方结算说明](https://help.polymarket.com/en/articles/13364518-how-are-prediction-markets-resolved)、[官方 Gamma SDK 状态模型](https://github.com/Polymarket/py-sdk/blob/main/src/polymarket/models/gamma/market.py)、[TennisMyLife 免费源](https://stats.tennismylife.org/tennis-match-database)。','']
    path=ROOT/'docs/大小分、完赛与扩展玩法-v2-2026-10-26.md';path.write_text('\n'.join(lines))
    print(json.dumps({'report':str(path),'completion':completion['probabilities'],'comparisons':comparisons,'coverage':data['coverage']},ensure_ascii=False))


if __name__=='__main__':main()
