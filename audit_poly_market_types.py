#!/usr/bin/env python3
"""Inventory every market in the completed public tennis event enumeration.

No predictions or settlement execution: legacy families are research labels.
Original contracts remain in the compressed source pages, referenced per row.
"""
import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import re

from core.data import ROOT, atomic_json

LABELS = {
    'moneyline': '单场胜负／晋级',
    'tennis_first_set_winner': '第一盘胜者',
    'tennis_set_winner': '指定盘胜者',
    'tennis_first_set_totals': '第一盘总局数大小',
    'tennis_set_games_totals': '指定盘总局数大小',
    'tennis_match_totals': '全场总局数大小',
    'tennis_set_totals': '全场总盘数大小',
    'tennis_game_handicap': '全场让局',
    'tennis_set_handicap': '全场让盘',
    'tennis_exact_score': '全场精确盘分（含未完成分支）',
    'tennis_completed_match': '比赛是否正常完成',
    'tournament_winner': '赛事夺冠（个人／组合／团体）',
    'olympic_gold': '奥运金牌（具体参赛项目以规则为准）',
    'reach_round': '指定选手晋级指定轮次',
    'qualify_finals': '取得年终总决赛资格',
    'year_end_ranking': '年终排名／年终第一',
    'ranking_points': '排名积分门槛',
    'win_a_major_in_year': '年度至少赢一次大满贯',
    'calendar_grand_slam': '年度包揽四大满贯',
    'more_grand_slams': '年度大满贯冠军数量比较',
    'participation': '是否参赛／出场',
    'retirement_announcement': '是否在期限前宣布退役',
    'suspension_duration': '禁赛时长区间',
    'any_match_win': '赛事期间是否至少赢一场（组合）',
    'qualifier_reach_round': '是否有资格赛选手晋级指定轮次',
    'wildcard_reach_round': '是否有外卡选手晋级指定轮次',
    'defeat_top_seed': '指定球员是否击败高种子',
    'top_seed_first_round_exit': '是否有高种子首轮出局',
    'racket_break': '是否有球员摔断球拍',
    'dress_code_violation': '是否违反着装规定',
    'code_violation': '指定球员是否收到违规处罚',
    'longest_match_duration': '赛事最长比赛时长门槛',
    'nationality_champion': '是否有指定国籍选手夺冠',
    'unbeaten_champion': '赛事冠军是否全胜',
    'celebrity_attendance': '指定人物是否到场观赛',
    'promotion_count': '关联品牌活动发放数量区间',
    'match_winner_and_game_margin': '赢得比赛且达到局差（历史复合条件）',
    'finalist_pair': '指定两名选手共同进入决赛',
    'unclassified': '尚待人工核对',
}

# Bespoke public contracts reviewed against their complete descriptions. These
# event IDs scope the exception; never apply a catch-all "win" regex to them.
LEGACY_EVENTS = {
    '11457': 'olympic_gold', '11458': 'olympic_gold',
    '11730': 'olympic_gold', '11768': 'olympic_gold',
    '11771': 'olympic_gold', '11773': 'olympic_gold',
    '17173': 'moneyline', '17176': 'moneyline', '38918': 'moneyline',
    '31905': 'match_winner_and_game_margin', '42440': 'tennis_match_totals',
    '31549': 'match_winner_and_game_margin', '31551': 'match_winner_and_game_margin',
    '31708': 'match_winner_and_game_margin', '31755': 'match_winner_and_game_margin',
    '32223': 'tennis_match_totals', '40300': 'finalist_pair',
    '903247': 'tournament_winner',
    '23994': 'win_a_major_in_year', '24442': 'win_a_major_in_year',
    '139296': 'more_grand_slams', '147463': 'calendar_grand_slam',
    '148000': 'calendar_grand_slam', '280841': 'participation',
    '576650': 'moneyline', '577862': 'participation', '608734': 'any_match_win',
    '623672': 'qualifier_reach_round', '623690': 'wildcard_reach_round',
    '623698': 'defeat_top_seed', '623700': 'racket_break',
    '623708': 'top_seed_first_round_exit', '623709': 'top_seed_first_round_exit',
    '623710': 'dress_code_violation', '623746': 'longest_match_duration',
    '623747': 'code_violation', '739714': 'retirement_announcement',
    '766238': 'qualify_finals', '768652': 'year_end_ranking',
    '768653': 'year_end_ranking', '775275': 'ranking_points',
    '806319': 'participation', '813144': 'celebrity_attendance',
    '882721': 'suspension_duration', '910418': 'promotion_count',
    '1000927': 'nationality_champion', '1075902': 'tournament_winner',
    '1140170': 'qualify_finals', '1140172': 'year_end_ranking',
    '1140173': 'unbeaten_champion', '1140189': 'participation',
    '46811': 'tournament_winner', '85692': 'tournament_winner',
}


def array(value):
    if value is None: return []
    if isinstance(value, str): value = json.loads(value)
    if not isinstance(value, list): raise ValueError('Expected array')
    return value


def family(event, market):
    native = market.get('sportsMarketType')
    if (native == 'moneyline' and re.search(r'\b(?:winner|champion)\b', event.get('title', ''), re.I)
            and {x.lower() for x in array(market.get('outcomes'))} == {'yes', 'no'}):
        return 'tournament_winner', 'native_moneyline_but_outright_event_and_binary_candidate'
    if native: return native, 'poly_sportsMarketType'
    eid = str(event['id']); title = event.get('title', '')
    if eid in LEGACY_EVENTS: return LEGACY_EVENTS[eid], 'reviewed_event_rule'
    if re.search(r'final\s+score.*sets', title, re.I):
        return 'tennis_exact_score', 'legacy_event_title'
    if re.search(r'(?:reach|to reach).*?(?:round|quarterfinal|semifinal|final)', title, re.I):
        return 'reach_round', 'legacy_event_title'
    if re.search(r'\b(?:winner|champion)\b', title, re.I):
        return 'tournament_winner', 'legacy_event_title'
    if re.search(r'\bvs\.?\s', title, re.I):
        outcomes = array(market.get('outcomes'))
        if len(outcomes) == 2 and {x.lower() for x in outcomes} != {'yes', 'no'}:
            return 'moneyline', 'legacy_match_title_and_named_outcomes'
    return 'unclassified', 'manual_review_required'


def parameters(market, kind):
    """Keep raw line separately; its meaning differs by market type."""
    text = market.get('question') or ''; group = market.get('groupItemTitle') or ''
    result = {}
    if kind in ('tennis_first_set_winner', 'tennis_first_set_totals'):
        result['set_number'] = 1
    elif kind in ('tennis_set_winner', 'tennis_set_games_totals'):
        found = re.search(r'\bset\s+(\d+)\b', text, re.I)
        result['set_number'] = int(found.group(1)) if found else None
    if kind in ('tennis_first_set_totals', 'tennis_set_games_totals', 'tennis_match_totals', 'tennis_set_totals'):
        result['threshold'] = market.get('line')
        if result['threshold'] is None:
            found = re.search(r'(?:over|o/u)\s+(\d+(?:\.\d+)?)', text, re.I)
            if found: result['threshold'] = float(found.group(1))
        result['unit'] = 'sets' if kind == 'tennis_set_totals' else 'games'
    if kind in ('tennis_game_handicap', 'tennis_set_handicap'):
        # Earlier markets can carry a positive raw line despite the first
        # named outcome being the negative handicap selection.
        found = re.search(r'(?:Set Handicap|Game Spread|Spread):\s*(.*?)\s*\(([+-]\d+(?:\.\d+)?)\)\s+vs\s+(.*?)\s*\(([+-]\d+(?:\.\d+)?)\)', text, re.I)
        result['named_handicaps'] = ([{'selection': found.group(1), 'handicap': float(found.group(2))},
                                      {'selection': found.group(3), 'handicap': float(found.group(4))}]
                                     if found else None)
        result['unit'] = 'games' if kind == 'tennis_game_handicap' else 'sets'
    if kind == 'tennis_exact_score':
        found = re.search(r'([23])\s*[-:]\s*([0-2])', group or text)
        result['score'] = [int(found.group(1)), int(found.group(2))] if found else None
        result['special_branch'] = ('not_completed' if re.search(r'not completed', group or text, re.I)
                                    else 'other' if re.search(r'\bother\b', group or text, re.I) else None)
    return result


def evidence_events(base, summary):
    """Read only sources used by the accepted complete enumeration."""
    excluded = {str(e['id']) for e in json.loads((ROOT / 'reports/poly-tennis-quarantine.json').read_text())}
    extras = {str(row['event']['id']) for row in summary['outside_root_decisions']
              if row['decision'] == 'confirmed_tennis'}
    manifest = json.loads((base / 'cross-check-manifest.json').read_text())
    if not manifest['all_pagination_exhausted']: raise ValueError('Incomplete cross checks')
    folders = [base / 'tennis-history']
    folders += [base / ('outside-root-tag-' + str(i)) for i in manifest['tag_seeds']]
    folders += [base / ('outside-root-series-' + str(i)) for i in manifest['series_seeds']]
    seen = set()
    for folder in folders:
        status = json.loads((folder / 'status.json').read_text())
        if not status['pagination_exhausted']: raise ValueError('Incomplete source ' + str(folder))
        for source in sorted(folder.glob('page-*.json.gz')):
            with gzip.open(source, 'rt') as handle: payload = json.load(handle)
            for event in payload['events']:
                eid = str(event['id'])
                if eid in seen or eid in excluded: continue
                if folder != folders[0] and eid not in extras: continue
                seen.add(eid)
                yield event, str(source.relative_to(ROOT))
    if len(seen) != summary['events']: raise ValueError('Accepted event count mismatch')


def build(base, output):
    summary = json.loads((ROOT / 'reports/poly-enumeration-summary.json').read_text())
    declared = json.loads((ROOT / 'data/market-audit/2026-10-26/market-types/declared-types.json').read_text())['marketTypes']
    output.mkdir(parents=True, exist_ok=True)
    native_counts = collections.Counter(); families = collections.Counter(); periods = collections.defaultdict(collections.Counter)
    lines = collections.defaultdict(collections.Counter); raw_event_sets = collections.defaultdict(set)
    family_event_sets = collections.defaultdict(set); examples = {}; latest = {}; legacy = {}; missing = []
    seen = {}; duplicates = 0; conflicts = []; events = 0; references = 0
    native_business_differences = collections.defaultdict(lambda: {'markets': 0, 'event_ids': set()})
    quality_issues = []
    index = output / 'poly-tennis-markets.ndjson.gz'
    temporary = index.with_suffix('.gz.tmp')
    with gzip.open(temporary, 'wt', encoding='utf-8', compresslevel=6) as handle:
        for event, source in evidence_events(base, summary):
            events += 1; eid = str(event['id'])
            for market in event.get('markets') or []:
                references += 1; mid = str(market['id']); native = market.get('sportsMarketType') or 'unspecified'
                kind, basis = family(event, market); params = parameters(market, kind)
                fingerprint = hashlib.sha256(json.dumps({k: market.get(k) for k in (
                    'conditionId', 'outcomes', 'clobTokenIds', 'question', 'description', 'sportsMarketType', 'line')},
                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                raw_event_sets[native].add(eid); family_event_sets[kind].add(eid)
                if mid in seen:
                    duplicates += 1
                    if seen[mid] != fingerprint: conflicts.append({'event_id': eid, 'market_id': mid, 'source': source})
                    continue
                seen[mid] = fingerprint
                native_counts[native] += 1; families[kind] += 1
                if native != 'unspecified' and native != kind:
                    mismatch = native_business_differences[native + ' -> ' + kind]
                    mismatch['markets'] += 1; mismatch['event_ids'].add(eid)
                lines[native][str(market.get('line'))] += 1
                if 'set_number' in params: periods[native][str(params['set_number'])] += 1
                url = 'https://polymarket.com/event/' + event['slug']
                row = {'event_id': eid, 'market_id': mid, 'condition_id': market.get('conditionId'),
                       'event_url': url, 'market_slug': market.get('slug'), 'sportsMarketType': market.get('sportsMarketType'),
                       'research_family': kind, 'classification_basis': basis, 'question': market.get('question'),
                       'groupItemTitle': market.get('groupItemTitle'), 'line_raw': market.get('line'),
                       'parameters': params, 'outcomes': array(market.get('outcomes')),
                       'clobTokenIds': array(market.get('clobTokenIds')), 'negRisk': market.get('negRisk'),
                       'negRiskMarketID': market.get('negRiskMarketID'), 'gameStartTime': market.get('gameStartTime'),
                       'marketMetadata': market.get('marketMetadata'),
                       'active': market.get('active'), 'closed': market.get('closed'),
                       'acceptingOrders': market.get('acceptingOrders'), 'parent_closed': event.get('closed'),
                       'source_page': source, 'contract_sha256': fingerprint,
                       'description_sha256': hashlib.sha256((market.get('description') or '').encode()).hexdigest()}
                warnings = []
                if len(row['outcomes']) != len(row['clobTokenIds']): warnings.append('outcomes_token_count_mismatch')
                for key, value in params.items():
                    if value is None and key not in ('score', 'special_branch'): warnings.append(key + '_unparsed')
                row['mapping_warnings'] = warnings
                if warnings: quality_issues.append({'event_id': eid, 'market_id': mid, 'warnings': warnings, 'source_page': source})
                handle.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
                sample = {**row, 'event_title': event['title'], 'description': market.get('description')}
                examples.setdefault(kind, sample)
                if kind not in latest or int(eid) >= int(latest[kind]['event_id']): latest[kind] = sample
                if native == 'unspecified':
                    item = legacy.setdefault(eid, {'event_id': eid, 'title': event['title'], 'url': url,
                                                  'families': collections.Counter(), 'markets': []})
                    item['families'][kind] += 1
                    item['markets'].append({k: sample[k] for k in ('market_id', 'question', 'research_family', 'classification_basis', 'groupItemTitle', 'parameters')})
                if kind == 'unclassified': missing.append(sample)
    temporary.replace(index)
    result = {'built_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'scope': summary['scope'], 'events': events, 'distinct_markets': len(seen),
              'market_references': references, 'duplicate_references': duplicates, 'contract_conflicts': conflicts,
              'native_type_counts': dict(native_counts), 'native_type_event_counts': {k: len(v) for k, v in raw_event_sets.items()},
              'research_family_counts': dict(families), 'research_family_event_counts': {k: len(v) for k, v in family_event_sets.items()},
              'declared_tennis_types': [t for t in declared if t.startswith('tennis_')],
              'declared_tennis_types_not_observed': [t for t in declared if t.startswith('tennis_') and t not in native_counts],
              'observed_types_not_declared': [t for t in native_counts if t != 'unspecified' and t not in declared],
              'raw_line_distributions': dict(lines), 'set_number_distributions': dict(periods),
              'unclassified_markets': len(missing), 'legacy_events': len(legacy),
              'native_business_differences': {k: {'markets': v['markets'], 'event_ids': sorted(v['event_ids'])}
                                              for k, v in native_business_differences.items()},
              'mapping_quality_issues': quality_issues,
              'index': str(index.relative_to(ROOT)),
              'note': 'Historical public API snapshot, not simultaneously tradable inventory. Research labels do not enable predictions or settlement. Original descriptions and source timestamps remain in source pages; labels are not official Poly enums.'}
    atomic_json(output / 'poly-tennis-market-types.json', result)
    atomic_json(output / 'poly-tennis-market-examples.json', {'first_in_source_scan': examples, 'highest_event_id': latest})
    atomic_json(output / 'poly-tennis-legacy-markets.json', list(legacy.values()))
    atomic_json(output / 'poly-tennis-markets-unclassified.json', missing)
    render_report(result, examples, latest, legacy, ROOT / 'docs/Poly网球全部玩法类型-2026-10-26.md')
    print(json.dumps({k: result[k] for k in ('events', 'distinct_markets', 'duplicate_references', 'native_type_counts', 'research_family_counts', 'unclassified_markets')}, ensure_ascii=False, indent=2))
    return result


def render_report(result, first, last, legacy, path):
    lines = ['# Poly 网球全部玩法类型核查 — 2026-10-26', '',
             '本报告使用已完成分页的网球历史目录，逐个读取原始事件内的全部 markets；同时读取官方 sports/market-types 枚举。包含已关闭盘口，不限实时开放比赛。', '',
             f"接受的网球事件 **{result['events']:,}** 个，按 market.id 去重后 **{result['distinct_markets']:,}** 个独立盘口。重复引用 {result['duplicate_references']} 个，合约字段冲突 {len(result['contract_conflicts'])} 个。", '',
             '根 Tennis 标签历史 48,244 个事件，剔除 9 个误标大学橄榄球事件，交叉查询补入 7 个缺少根标签的温网／巴塞罗那网球事件。详见完整分类枚举报告。', '',
             '历史扫描完成于 2026-10-26 02:27 北京时间，交叉核查完成于 02:30；官方玩法枚举另存查询时间。扫描期间源会变化，以下数量不能当作同一时刻可交易盘口数。', '',
             '## 官方类型与历史实际出现情况', '',
             '官方枚举提供 10 个 tennis_ 专用类型，本次历史全部出现；另有通用 moneyline。unspecified 是本地对缺失 sportsMarketType 的记录标签，不是官方第 12 种玩法。', '',
             '| Poly 原始 sportsMarketType | 含义 | 独立盘口数 | 涉及事件数 |',
             '| --- | --- | ---: | ---: |']
    for kind in LABELS:
        if kind not in result['native_type_counts']: continue
        lines.append(f"| `{kind}` | {LABELS[kind]} | {result['native_type_counts'][kind]:,} | {result['native_type_event_counts'][kind]:,} |")
    lines += [f"| 未标注 | 历史自定义盘及旧格式 | {result['native_type_counts']['unspecified']:,} | {result['legacy_events']:,} |", '',
              '同一事件可包含多种玩法，事件数不能按列相加。盘口数不同于比赛数：不同大小分线、让分方向、精确盘分候选分别计数。', '',
              '## 本次实际观察的参数', '',
              '| 类型 | 历史参数取值 |', '| --- | --- |']
    for kind, counts in result['raw_line_distributions'].items():
        observed = [k for k in counts if k != 'None']
        if observed: lines.append(f"| `{kind}` 的原始 line | " + '、'.join(sorted(observed, key=float)) + ' |')
    lines += ['', '注意 `tennis_set_winner.line=2/3/4` 表示第几盘，不是大小分线。指定盘胜者和指定盘总局数实际观察到第 2、3、4 盘；第一盘另有专用类型。本次未观察到第 5 盘对应记录，不能据此断言平台永远不提供。', '',
              '第一盘总局数与指定盘总局数属于相同统计量的不同原始类型；必须保留 set_number。全场总盘数的单位是 sets，全场总局数的单位是 games。', '',
              '让盘原始 line 历史同时有正负数：例如 market 671845 的 line=+1.5，但标题为 Sinner(-1.5) 对 Zverev(+1.5)。必须结合选项、标题及规则确认让分对象，不能直接把 line 赋给数组第一名球员。索引同时保留原始值与标题解析值，后者只是研究字段。', '',
              '精确盘分是整场的盘比分，不是某盘 6-4 的局比分。本次原生精确盘分出现在 130 个五盘制事件，共 910 个二元候选盘：双方各 3-0／3-1／3-2，加 Not Completed，共七个分支。老格式另有 Other 分支，应以该事件完整候选与规则为准。', '',
              '## 核对后的业务玩法目录', '',
              f"合并旧格式后，按本项目研究粒度整理为 **{len(result['research_family_counts'])} 个业务类别**。这是研究分类，不是 Poly 官方枚举数量。已将全部 {result['native_type_counts']['unspecified']:,} 个未标注盘口分配到类别；分类不代表已实现预测或结算逻辑。", '',
              '| 内部研究类别 | 中文含义 | 盘口数（含新旧格式） | 示例 |', '| --- | --- | ---: | --- |']
    for kind, count in result['research_family_counts'].items():
        example = first[kind]
        lines.append(f"| `{kind}` | {LABELS.get(kind, kind)} | {count:,} | [market {example['market_id']}]({example['event_url']}) |")
    lines += ['', '原始字段与业务语义不同的例子：7 个赛事的 419 个夺冠候选盘也被标为 moneyline。上海、宁波、阿拉木图、大阪、布鲁塞尔、东京、广州均有此情况。底表保留原始类型，业务分类改为 tournament_winner，避免当成单场两人胜负。', '',
              '历史复合局差盘要求“赢得整场且局差达到门槛”，本次 5 个；不直接并入标准让局。US Open Final: Sinner vs. Alcaraz?（event 40300）问两人能否共同进入决赛，不是两人交手谁赢。', '',
              '## 结算规则必须逐盘口保留', '',
              '- moneyline：老版本可能按赛前弃权后的晋级方结算，较新版本会对赛前 walkover 结算 50-50；开始后的退赛／取消资格又可能按晋级方结算。不能共用一条固定规则。',
              '- 第一盘／指定盘胜者：该盘完成后可按该盘胜者结算；该盘未开始或未完成通常有 50-50 条款，具体延期截止日期以合约为准。',
              '- 局数／盘数大小和让盘／让局：新版本包含“虽未完成但结果已无条件确定”的例外；旧版本可能直接 50-50，也有按中止时官方比分或 No 结算的旧自定义盘。',
              '- 抢七通常按一局计；替代决胜盘的 match/super tiebreak 还涉及按一局或一盘计的不同统计单位。必须按赛事赛制和具体规则执行。',
              '- Completed Match：正常完成为 Yes，退赛、弃权等通常为 No；这是独立事件概率。不能用当前条件于正常完赛的胜率代替。',
              '- Exact Score：Not Completed／Other 是候选分支；每个候选本身仍可能是 Yes/No 二元盘口，不应把分组文字当成这个盘口的 outcomes 数组。',
              '- 取消与延期截止日期存在固定日期、7 天、14 天等版本；最终以每个合约 description 为准。', '',
              '以下新旧示例保留了完整规则原文，可直接在 examples JSON 和原始 source_page 中核对；本报告仅做释义，不是结算引擎。', '',
              '| 类型 | 扫描中较早示例 | 事件 ID 最大的示例 |', '| --- | --- | --- |']
    for kind in result['native_type_counts']:
        if kind == 'unspecified': continue
        a = first[kind]; b = last[kind]
        lines.append(f"| `{kind}` | [market {a['market_id']}]({a['event_url']}) | [market {b['market_id']}]({b['event_url']}) |")
    lines += ['', '事件 ID 最大的示例不能当作规则最后更新时间。原始扫描先读取根目录，再补充交叉查询事件。示例是观察证据，不是整个类型的统一规则模板。', '',
              '## 映射数据异常', '',
              f"全量索引检查发现 {len(result['mapping_quality_issues'])} 个盘口有映射字段异常，具体 ID 与 source_page 保存在汇总的 mapping_quality_issues 和逐盘口 mapping_warnings 中。", '',
              '本轮为 market 518778、518892：有 Yes/No 选项，但 clobTokenIds 缺失、acceptingOrders 未提供，不能据此创建可交易选项映射。event 仍属合法研究范围，不从玩法统计中静默删除。', '',
              '历史 market 676669 标题前缀是 Spread 而非 Set Handicap；经原文确认其统计量是盘数，解析已兼容此旧格式，不能仅凭 Spread 一词判为让局。', '',
              '## ForeGate 映射与模型边界', '',
              '建议以 event.id + market.id + conditionId 标识具体合约，以每个盘口自己的 outcomes 与 clobTokenIds 数组顺序绑定选项，保留 sportsMarketType、research_family、set_number、盘口线／让分对象、精确比分候选、negRisk 分组和 description 哈希。不能用 event 名称或球员顺序替代 outcome 身份。', '',
              '当前模型只实现成人 ATP/WTA 主巡回赛单打、正常完成条件下的赛前全场胜负概率。它尚不能直接给上述非胜负玩法定价，也没有解决单场胜负对退赛／弃权的合约口径差异。', '',
              '下一阶段的基础是按赛制建立发球分→局→盘→全场的联合比分分布，才能一致计算盘胜者、让局／让盘、大小局／大小盘、精确盘分；另需独立处理未完成风险。夺冠／晋级需要签表与整站模拟，排名／参赛／纪律／周边事件应独立建模或明确返回不支持。不能把现有胜率简单换算成所有玩法概率。', '',
              '## 可复核产物与运行', '',
              '- `audit_poly_market_types.py`：读取完整历史证据、按 market.id 去重、提取全部盘口及研究分类。',
              '- `reports/poly-tennis-market-types.json`：官方类型对照、数量、参数分布、原始类型与业务类型差异。',
              '- `reports/poly-tennis-markets.ndjson.gz`：570,149 行完整盘口索引，保留选项／Token／条件 ID 及原始页面位置。原文规则留在 source_page 压缩响应，索引有 description_sha256 可核对；约 137 MiB，作为本地研究制品，不提交 Git。',
              '- `reports/poly-tennis-market-examples.json`：各类较早／扫描最后示例与完整规则。',
              '- `reports/poly-tennis-legacy-markets.json`：821 个旧格式事件及全部候选问题。',
              '- `reports/poly-tennis-markets-unclassified.json`：本轮为空；未来新问题无法识别时保留待核对，不默认归胜负盘。', '',
              '```bash',
              "python3 -B -c \"from pathlib import Path; from audit_polymarket import get; get('/sports/market-types', Path('data/market-audit/2026-10-26/market-types/declared-types.json'))\"",
              'python3 -B audit_poly_market_types.py',
              'python3 -B -m unittest discover -s tests -q', '```', '',
              '首次建立历史缓存需先按完整分类枚举报告运行 enumerate_poly_tennis.py 和 build_poly_enumeration.py。重建玩法索引无需重新抓取全部历史。', '',
              '## 范围限制与官方来源', '',
              '本次穷尽的是此前已核查目录所返回的公开事件与其 markets，加上当前官方网球专用枚举。不能宣称覆盖删除／私有／未发布市场或未来新类型。服务器对 active=false、archived=true 的旧探测未遵守过滤参数，不能据此判断这些分支为空；本轮不依赖它们，只读取无状态过滤的已完成历史分页。未观察到的 ace、双误、逐分、下一局等玩法不补造为已支持。', '',
              '- [官方玩法枚举接口说明](https://docs.polymarket.com/api-reference/sports/get-valid-sports-market-types)',
              '- [官方当前玩法枚举响应](https://gamma-api.polymarket.com/sports/market-types)',
              '- [官方事件游标分页](https://docs.polymarket.com/api-reference/events/list-events-keyset-pagination)',
              '- [完整分类枚举及分页证据](Poly网球完整分类枚举-2026-10-26.md)', '',
              '## 旧格式中非单场胜负的逐事件附录', '',
              '| event.id | 事件 | 研究类别与盘口数 |', '| --- | --- | --- |']
    for eid, item in legacy.items():
        if set(item['families']) == {'moneyline'}: continue
        title = item['title'].replace('|', '\\|')
        detail = '；'.join(f"{LABELS.get(k, k)} × {v}" for k, v in item['families'].items())
        lines.append(f"| {eid} | [{title}]({item['url']}) | {detail} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT / 'data/market-audit/2026-10-26/enumeration')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports')
    args = parser.parse_args(); build(args.source, args.output)
