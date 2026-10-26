"""Honest capability matrix: research capability is not production coverage."""
import json
from .data import ROOT
from .scoring import SCORE_TYPES

DRAW_TYPES = ('tournament_winner','reach_round','finalist_pair','qualifier_reach_round',
              'wildcard_reach_round','top_seed_first_round_exit','nationality_champion','defeat_top_seed','any_match_win')
BASELINE_TYPES=('tennis_completed_match',)
GAPS = {
    'olympic_gold': '需要奥运项目及资格／签表；部分盘口涵盖单双打等多个项目，当前仅成人巡回赛单打。',
    'win_a_major_in_year': '需要全年四站赛程、参赛概率、完整签表与跨赛事依赖，不能用当前胜率直接外推。',
    'calendar_grand_slam': '需要四大满贯联合赛季模拟及参赛／退赛风险。',
    'more_grand_slams': '需要两名选手全赛季冠军数量的联合分布及平局结算。',
    'participation': '需要官方报名／退赛／出场信息和独立参赛概率模型。',
    'retirement_announcement': '需要公告、新闻等独立事件模型；历史赛果不能可靠估计。',
    'suspension_duration': '需要纪律案件信息和独立事件模型。',
    'racket_break': '需要可靠的球员行为事件记录，现有免费赛果无此标签。',
    'dress_code_violation': '需要着装违规历史及现场裁判信息，现有赛果不包含。',
    'longest_match_duration': '需要整站时长极值模型，准确时长、雨停和赛制信息；局数不能直接当时长。',
    'code_violation': '需要裁判／行为事件记录，现有免费赛果无此标签。',
    'qualify_finals': '需要完整积分规则、剩余赛历、报名、伤病与赛季模拟；不能用年终排名快照替代。',
    'year_end_ranking': '需要赛季积分保分／新增与剩余赛历联合模拟。',
    'ranking_points': '需要积分规则、参赛安排及赛季积分路径模拟。',
    'celebrity_attendance': '独立娱乐／新闻事件，球员竞技模型无法估计。',
    'promotion_count': '需要品牌活动规则与执行数据，网球比分不足以预测。',
    'unbeaten_champion': '当前签表引擎仅单淘汰；ATP Finals 需要循环小组赛、晋级与递补规则。',
}


def coverage(model_scope='main_tour'):
    from audit_poly_market_types import LABELS
    inventory=ROOT/'reports/poly-tennis-market-types.json'
    counts=json.loads(inventory.read_text())['research_family_counts'] if inventory.exists() else {}
    rows=[]
    for kind in list(SCORE_TYPES)+list(DRAW_TYPES)+list(BASELINE_TYPES)+list(GAPS):
        mode='experimental_completed_match' if kind in SCORE_TYPES else 'experimental_supplied_draw' if kind in DRAW_TYPES else 'historical_base_rate' if kind in BASELINE_TYPES else 'unavailable'
        score_scope='成人 ATP 主巡回赛、Challenger 正赛、ATP 资格赛标准单打' if model_scope=='expanded_atp' else '成人 ATP/WTA 主巡回赛标准单打'
        reason=(f'已实现比分分布和条件概率；当前加载范围为{score_scope}，需明确盘制及抢七规则。'
                if kind in SCORE_TYPES else '已实现签表条件推演；需调用方提供并核实完整单淘汰签表、球员和相关属性。自动获取／核验签表尚未实现。'
                if kind in DRAW_TYPES else '已从明确结算的 Poly 完赛合约建立整体历史基线，包含取消等 No；无选手伤病信息，不是个体精确风险。'
                if kind in BASELINE_TYPES else GAPS[kind])
        if kind=='tennis_exact_score':reason+=' Not Completed 可用独立完赛基线估计；Other 仍需明确所列比分及具体合约规则。'
        if kind=='any_match_win':reason+=' 只支持单打目标球员集合；观察到的双打合约仍不适用。'
        if kind=='defeat_top_seed':reason+=' 已计算指定球员在任意轮次击败高种子的路径联合事件，须完整核实种子资料。'
        if kind=='nationality_champion':reason+=' 当前只输出单张签表的国籍冠军分布，跨 ATP/WTA 的 OR 合约尚需组合。'
        rows.append({'family':kind,'label':LABELS[kind],'historical_markets':counts.get(kind),
                     'status':mode,'reason':reason,'contract_ready':False})
    return {'families':rows,'score_families':len(SCORE_TYPES),'draw_families':len(DRAW_TYPES),
            'baseline_families':len(BASELINE_TYPES),'unavailable_families':len(GAPS),'production_contract_ready_families':0,
            'loaded_model_scope':model_scope,'separate_research_scope':'expanded_atp: models/expanded/current.json, not loaded by default',
            'note':'38 个业务研究类别。玩法计算能力不等于 Poly 事件／球员覆盖率。Challenger 资格赛、ITF、双打和青少年仍缺少已验证模型；Challenger 正赛及 ATP 资格赛须显式加载扩展快照。'}
