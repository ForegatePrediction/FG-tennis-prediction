#!/usr/bin/env python3
"""Build an evidence-backed taxonomy from exhausted public dictionaries/history."""
import collections
import datetime as dt
import json
from pathlib import Path
import re

from core.data import ROOT, atomic_json

MAJORS = [
    ('australian_open', '澳大利亚网球公开赛', [866, 103046], r'\b(?:australian open|australia open)\b'),
    ('roland_garros', '法国网球公开赛 / Roland Garros', [102106, 103047], r'\b(?:french open|roland garros)\b'),
    ('wimbledon', '温布尔登网球锦标赛', [100290], r'\bwimbledon\b'),
    ('us_open', '美国网球公开赛', [100408], r'\b(?:u\.?s\.? open|united states open)\b'),
]
TAG_CANDIDATE = re.compile(r'tennis|wimbledon|australian.open|french.open|roland.garros|\b(?:atp|wta|itf)\b|davis.cup|daviscup|billie.jean|bjkcup|laver.cup|grand.slam', re.I)
EXCLUDE_TAG_SLUGS = {'table-tennis', 'ttolympics', 'ttcl', 'tteuropecup', 'us-open-golf', 'usoc'}


def known_other_sport(event):
    sports = {'cfb', 'nfl', 'nba', 'mlb', 'nhl', 'soccer', 'epl', 'table-tennis'}
    if (event.get('sport') or {}).get('sport') in sports: return True
    return any(any((s.get('slug') or '') == sport or (s.get('slug') or '').startswith(sport + '-') for sport in sports)
               for s in event.get('series') or [])


def outside_root_decision(event):
    slugs = {t.get('slug') for t in event.get('tags') or []}
    if known_other_sport(event) or slugs & {'golf', 'pga', 'pga-tour', 'table-tennis', 'usoc', 'baseball', 'mlb'}:
        return 'excluded_other_sport'
    sport = (event.get('sport') or {}).get('sport')
    if sport in {'atp', 'wta', 'atp-doubles', 'wta-doubles', 'itf', 'wimbledon', 'daviscup', 'bjkcup'}:
        return 'confirmed_tennis'
    if slugs & {'australian-open', 'ao', 'french-open', 'roland-garros', 'wimbledon', 'atp', 'wta', 'itf', 'daviscup', 'bjkcup', 'laver-cup', 'barcelona-open'}:
        return 'confirmed_tennis'
    return 'unresolved'


def major_key(event):
    # Root Tennis membership is checked by the caller; the US Open tag alone
    # is shared with golf. Prefer actual competition context over unrelated tags.
    text = ' '.join([event.get('title') or '', event.get('league_raw') or ''])
    for key, _, _, pattern in MAJORS:
        if re.search(pattern, text, re.I): return key, 'competition_name'
    ids = {str(t['id']) for t in event.get('tags') or []}
    for key, _, tags, _ in MAJORS:
        if ids & {str(t) for t in tags}: return key, 'tag_only'
    return None, None


def competition(event):
    meta = event.get('metadata') or {}
    if meta.get('league'): return meta['league'], 'eventMetadata.league'
    title = event.get('title') or ''
    if ':' in title and re.search(r'\bvs\.?\s', title, re.I): return title.split(':', 1)[0], 'title_prefix'
    return None, None


def axes(event):
    league, _ = competition(event)
    text = league or ''
    meta = event.get('metadata') or {}
    sport = (event.get('sport') or {}).get('sport') or 'unknown'
    intro = ' '.join([text, meta.get('tennisFixtureSource') or ''])
    if meta.get('format') in ('singles', 'doubles'): discipline = meta['format']
    elif 'doubles' in sport or re.search(r'\bdoubles\b', text, re.I): discipline = 'doubles'
    elif sport in ('atp', 'wta', 'itf'): discipline = 'singles_hint'
    else: discipline = 'unknown'
    gender = 'male' if sport in ('atp', 'atp-doubles', 'daviscup') else 'female' if sport in ('wta', 'wta-doubles', 'bjkcup') else 'unknown'
    if gender == 'unknown':
        if re.search(r'\b(?:boys|men|mens)\b', text, re.I) or re.match(r'^M\d+\b', text): gender = 'male_hint'
        elif re.search(r'\b(?:girls|women|womens)\b', text, re.I) or re.match(r'^W\d+\b', text): gender = 'female_hint'
    return {'sport': sport, 'discipline': discipline, 'gender': gender,
            'junior': bool(re.search(r'\bjuniors?\b', text, re.I)),
            'qualifying': bool(re.search(r'\bqualif(?:ying|ication)\b', intro, re.I)),
            'itf_grade_prefix': (re.match(r'^([MW]\d+)\b', text).group(1) if re.match(r'^([MW]\d+)\b', text) else None)}


def build(folder):
    def read(path): return json.loads(path.read_text())
    statuses = {kind: read(folder / kind / 'status.json') for kind in ('tags', 'series', 'tennis-history')}
    if not all(s['pagination_exhausted'] for s in statuses.values()): raise ValueError('Enumeration incomplete; do not publish as complete')
    cross_manifest = read(folder / 'cross-check-manifest.json')
    if not cross_manifest['all_pagination_exhausted']: raise ValueError('Cross-checks incomplete')
    tags = {str(t['id']): t for t in read(folder / 'tags/dictionary.json')}
    series_dictionary = read(folder / 'series/dictionary.json')
    events = read(folder / 'tennis-history/events-compact.json')
    ids = {e['id'] for e in events}
    if len(events) != len(ids) or len(ids) != statuses['tennis-history']['unique_events']:
        raise ValueError('History count does not match completed pagination')
    root_count = len(events)
    quarantined = [e for e in events if known_other_sport(e)]
    events = [e for e in events if not known_other_sport(e)]
    supplements = []
    for path in sorted(folder.glob('tag-*/status.json')):
        status = read(path)
        rows = read(path.parent / 'events-compact.json')
        extra = [e for e in rows if e['id'] not in ids]
        supplements.append({'tag': status['query']['tag_id'], 'status': status,
                            'outside_root_events': len(extra), 'outside_root_examples': extra[:10]})
    outside = {}; outside_statuses = []
    cross_paths = [folder / f'outside-root-tag-{identifier}/status.json' for identifier in cross_manifest['tag_seeds']]
    cross_paths += [folder / f'outside-root-series-{identifier}/status.json' for identifier in cross_manifest['series_seeds']]
    if len(cross_paths) != cross_manifest['queries']: raise ValueError('Cross-check manifest count mismatch')
    for path in cross_paths:
        status = read(path)
        if not status['pagination_exhausted']: raise ValueError('Cross-check enumeration incomplete')
        outside_statuses.append(status)
        for event in read(path.parent / 'events-compact.json'):
            if event['id'] not in ids: outside[event['id']] = event
    decisions = [{'decision': outside_root_decision(e), 'event': e} for e in outside.values()]
    confirmed_extra = [r['event'] for r in decisions if r['decision'] == 'confirmed_tennis']
    events.extend(confirmed_extra)
    tag_events = collections.defaultdict(list); series_events = collections.defaultdict(list); league_events = collections.defaultdict(list)
    families = collections.defaultdict(list)
    for event in events:
        for tag in event.get('tags') or []: tag_events[str(tag['id'])].append(event)
        for series in event.get('series') or []: series_events[str(series['id'])].append(event)
        league, source = competition(event)
        if league:
            league_events[((event.get('sport') or {}).get('sport') or 'unassigned', league, source)].append(event)
        family, basis = major_key(event)
        if family: families[family].append((event, basis))
    candidate_ids = {i for i, t in tags.items() if TAG_CANDIDATE.search(t.get('label', '') + ' ' + t.get('slug', '')) and t.get('slug') not in EXCLUDE_TAG_SLUGS}
    candidate_ids |= {'100408', '103046'} & tags.keys()
    tag_rows = []
    for identifier in sorted(set(tag_events) | candidate_ids, key=int):
        raw = tags.get(identifier) or next(t for e in tag_events[identifier] for t in e['tags'] if str(t['id']) == identifier)
        sample = tag_events[identifier]
        tag_rows.append({**raw, 'catalog_events': len(sample), 'dictionary_keyword_candidate': identifier in candidate_ids,
                         'example_event_ids': [e['id'] for e in sample[:3]]})
    series_rows = []
    for row in series_dictionary:
        identifier = str(row['id'])
        if identifier in series_events or row.get('slug') == 'tennis' or TAG_CANDIDATE.search(row.get('title', '')) and 'table tennis' not in row.get('title', '').lower():
            series_rows.append({k: v for k, v in row.items() if k != 'event_summaries'} | {'catalog_events': len(series_events[identifier])})
    league_rows = []
    for (sport, league, source), sample in sorted(league_events.items()):
        league_rows.append({'poly_sport': sport, 'league_raw': league, 'source': source, 'events': len(sample),
                            'issues': ['league_contains_matchup'] if re.search(r'\bvs\.?\s', league, re.I) else [],
                            'example_event_id': sample[0]['id'], 'example_slug': sample[0].get('slug'),
                            'series_ids': sorted({str(s['id']) for e in sample for s in e.get('series') or []}),
                            'major_families': sorted({major_key(e)[0] for e in sample if major_key(e)[0]}),
                            'qualifying_seen': any(axes(e)['qualifying'] for e in sample),
                            'junior_seen': any(axes(e)['junior'] for e in sample)})
    major_rows = []
    for key, name, tag_ids, _ in MAJORS:
        sample = families[key]; event_axes = [axes(e) for e, _ in sample]
        major_rows.append({'key': key, 'name': name, 'tag_ids': tag_ids, 'events': len(sample),
                           'classification_basis': dict(collections.Counter(b for _, b in sample)),
                           'sports_observed': dict(collections.Counter(x['sport'] for x in event_axes)),
                           'disciplines_observed': dict(collections.Counter(x['discipline'] for x in event_axes)),
                           'junior_seen': any(x['junior'] for x in event_axes), 'qualifying_seen': any(x['qualifying'] for x in event_axes),
                           'competition_labels': sorted({competition(e)[0] for e, _ in sample if competition(e)[0] and not re.search(r'\bvs\.?\s', competition(e)[0], re.I)}),
                           'example_event_ids': [e['id'] for e, _ in sample[:5]]})
    all_axes = [axes(e) for e in events]
    filter_probes = []
    for name, field, expected in [('inactive', 'active', False), ('archived', 'archived', True)]:
        path = folder / (name + '-probe.json')
        if path.exists():
            sample = read(path).get('events', [])
            filter_probes.append({'query_field': field, 'requested': expected, 'returned_values': [e.get(field) for e in sample],
                                  'matches_requested_status': all(e.get(field) == expected for e in sample)})
    summary = {'built_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'scope': statuses, 'cross_check_manifest': cross_manifest,
               'explicit_status_filter_probes': filter_probes,
               'note': 'Exhausted returned public root-tag history and dictionaries, not proof of deleted, untagged, private or future events. Raw tournament labels are not canonical tournament identities.',
               'events': len(events), 'root_events': root_count, 'root_excluded_conflicts': len(quarantined), 'confirmed_extra_events': len(confirmed_extra),
               'outside_root_cross_checks': outside_statuses, 'outside_root_decisions': decisions,
               'event_created_range': [min(e['createdAt'] for e in events if e.get('createdAt')), max(e['createdAt'] for e in events if e.get('createdAt'))],
               'observed_tag_records': len(tag_events), 'dictionary_keyword_candidates': len(candidate_ids),
               'observed_series': len(series_events), 'tennis_series_dictionary_records': len(series_rows),
               'competition_label_rows': len(league_rows), 'competition_labels_unique': len({r['league_raw'] for r in league_rows}),
               'sports_observed': dict(collections.Counter(x['sport'] for x in all_axes)),
               'event_status_combinations': dict(collections.Counter(f"active={e.get('active')},closed={e.get('closed')}" for e in events)),
               'itf_grade_prefixes_observed': sorted({x['itf_grade_prefix'] for x in all_axes if x['itf_grade_prefix']}),
               'market_types_observed': sorted({t for e in events for t in e['market_types']}),
               'majors': major_rows, 'tag_cross_checks': supplements}
    outputs = {'poly-enumeration-summary.json': summary, 'poly-tennis-tags-all.json': tag_rows,
               'poly-tennis-series-all.json': series_rows, 'poly-tennis-competitions-all.json': league_rows,
               'poly-tennis-quarantine.json': quarantined}
    for name, data in outputs.items(): atomic_json(ROOT / 'reports' / name, data)
    write_report(summary, tag_rows, series_rows, league_rows, events)
    return summary


def write_report(summary, tags, series, leagues, events):
    def cell(value): return str(value).replace('|', '\\|').replace('\n', ' ')
    def table(headers, rows):
        return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                         ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows])
    status = summary['scope']
    lines = ['# Poly 网球完整分类枚举核查（含历史）', '',
             '核查日：2026-10-26（北京时间）。本报告取代上一版“8 个入口 + 当前开放赛事”的分类完整性结论；上一版仍可作为当时开放状态的快照。', '',
             '**四大满贯全部列入分类：澳网、法网／Roland Garros、温网、美网。** Poly 的 sport、series、tags 和具体赛事名称是交叉维度；不能把当前 `/sports` 的八个网球入口当成完整赛事枚举。', '',
             '## 一、遍历范围与完成证据', '',
             table(['目录', '不限定状态的记录数', '分页数', '完成依据'], [
                 ['全站 tags 字典', status['tags']['records'], status['tags']['pages'], 'offset 按实际返回条数递增，最终空页'],
                 ['全站 series 字典', status['series']['records'], status['series']['pages'], 'offset 按实际返回条数递增，最终空页'],
                 ['Tennis 总标签 864 历史事件', summary['root_events'], status['tennis-history']['pages'], 'id 升序游标遍历到 next_cursor 消失']]), '',
             f"三项均未传 active、closed、archived 状态过滤。另对 {len(summary['outside_root_cross_checks'])} 个已发现标签／系列执行排除 Tennis 总标签的交叉查询，找回 {summary['confirmed_extra_events']} 个可确认的历史网球事件；隔离 {summary['root_excluded_conflicts']} 个误带 Tennis 标签的其他运动事件。去重后的核查目录共 {summary['events']} 个事件，包含单场、冠军和其他合约。", '',
             f"源事件 createdAt 范围为 {summary['event_created_range'][0]} 至 {summary['event_created_range'][1]}。这是创建字段范围，不是实际比赛日期范围。各查询时间、URL、响应头和压缩原始页面保存在 `data/market-audit/2026-10-26/enumeration/`。", '',
             '交叉查询使用已观察到的专属标签与系列；Sports、Culture、Celebrities 等广义标签不倒扫全站，跳过清单保存在 cross-check-manifest.json。完成范围是这些公开 API 实际返回的字典和历史，无法证明被删除、未标记、不可访问或尚未发布的赛事；也不能由历史有盘口推断未来每一场都会开盘。', '',
             '接口边界复核：另行传 active=false、archived=true 的探测均返回了不符合所传状态的记录，说明本次不能依靠这些参数验收隐藏状态分支是否为空。原始探测已保存；本报告只称公开 API 返回历史已到末页，不声称内部数据库或不可访问分支已穷尽。', '',
             '## 二、四大满贯枚举', '',
             table(['赛事', '已核实 Poly 标签 ID', '关联事件数（含冠军合约）', '已观察具体赛事标签'],
                   [[m['name'], ', '.join(map(str, m['tag_ids'])), m['events'], '；'.join(m['competition_labels']) or '仅标题／合约标签'] for m in summary['majors']]), '',
             '同一大满贯内部应继续区分男子／女子、单打／双打、成人／青少年、资格赛／正赛、单场／冠军合约。表中列出实际发现的源标签；没有出现的分项保持未确认，不把四大满贯的全部理论组别写成 Poly 已开盘。关联事件数还可能包含出席人物等周边合约，不代表同样数量的比赛。', '',
             '## 三、巡回赛、团体赛及其他范围', '',
             '巡回赛入口包含 ATP、WTA、ITF、ATP Doubles、WTA Doubles；国家队入口包含 Davis Cup、Billie Jean King Cup；温网另有跨巡回赛的独立系列。全量系列字典还包含一个通用 Tennis 系列，详见下表。', '',
             table(['series ID', '原始名称', 'slug', '本轮目录关联事件数'],
                   [[s['id'], s.get('title'), s.get('slug'), s['catalog_events']] for s in series]), '',
             '具体赛事的完整原始枚举在第七节，不再用巡回赛名称代替赛事名称。挑战赛可以归在 ATP／WTA 入口；ATP 入口也不能保证都是成人正赛。赛事等级、具体赛事、性别、单／双打、年龄组与阶段必须分别存储。', '',
             '历史额外范围核查：', '',
             table(['范围', '匹配方式', '本轮目录事件数'], [
                 [label, '具体赛事上下文', sum(bool(re.search(pattern, (competition(e)[0] or e.get('title') or '').split(':', 1)[0], re.I)) for e in events)]
                 for label, pattern in [('ATP Finals', r'\batp finals\b'), ('WTA Finals', r'\bwta finals\b'), ('Davis Cup', r'\bdavis cup\b'),
                                        ('Billie Jean King Cup', r'\bbillie jean king cup\b'), ('Laver Cup', r'\blaver cup\b'),
                                        ('United Cup', r'\bunited cup\b'), ('Hopman Cup', r'\bhopman cup\b'), ('Six Kings Slam', r'\bsix kings\b'),
                                        ('Battle of the Sexes', r'\bbattle of the sexes\b'), ('Garden Cup', r'\bgarden cup\b')]]), '',
             '0 表示本轮未发现实际事件，不能删除已存在的元数据入口，也不能写成已验证有预测覆盖。历史另有巴黎奥运网球冠军／金牌合约，例如事件 11457、11730、11768、11771、11773；其共享标签 100248 当前已改名为 “2026 Winter Games”，不能用标签当前文字把历史网球赛事误归为冬奥。', '',
             '## 四、标签不能直接充当等级树', '',
             '已发现的赛事标签包括四大满贯、ATP Finals、ATP 250、Miami Open、Monte-Carlo、Madrid Open、BNP Paribas Open、Indian Wells、上海大师赛及多个城市／赞助商赛事名。并非每场赛事都带自己的独立标签，很多具体赛事只能从 eventMetadata.league 或历史标题获得。', '',
             '- Grand Slam 标签 102118 本轮独立查询仅返回高尔夫事件 “Jordan Spieth Grand Slam?”。我们可以在内部将四大满贯归为 Grand Slam，但不能把这个 Poly 标签当成网球等级枚举。',
             '- 根标签 864 也有误标：事件 44048、44051 等的 sport 或 series 指向大学橄榄球，已隔离；相反，5 个温网事件和巴塞罗那公开赛历史事件缺少根标签，需由其他标签找回。',
             '- US Open 标签 100408 同时用于高尔夫；需联合运动、具体赛事和规则确认。',
             '- ATP 与男子双打共用主标签，WTA 与女子双打也共用主标签；seriesType=single 也不代表网球单打。',
             '- 共现标签还包含球员姓名、Games、Sports 和编辑标签。下面的全标签附录会完整保留，但不宣称它们全是联赛分类。', '',
             f"本轮观察到 ITF 名称前缀：{', '.join(summary['itf_grade_prefixes_observed']) or '无明确前缀'}。未带前缀的 ITF 城市名称不自动推断等级；ATP/WTA 的官方等级也需另用赛历核验，不能仅凭城市名猜测。", '',
             '## 五、ForeGate 使用方式', '',
             '先保留 Poly 原始 tag ID、series ID、sport、event ID、league_raw 和来源，再映射 ForeGate 的分类。四大满贯设为完整赛事家族，巡回赛、性别、单双打、年龄和阶段作为独立属性。后续出现未知赛事名时先入目录并标记待映射，不能因为不在旧白名单里而丢弃。', '',
             '每个具体赛事再关联参与者、模型历史球员 ID、场地、盘制和合约玩法。ForeGate 继续从现有详情页直接调用预测 API。赛事目录存在、球员身份匹配、免费历史更新、模型可预测四项分别验收；本次只确认分类与历史发现范围。', '',
             '## 六、机器可读文件与复现', '',
             '- `reports/poly-enumeration-summary.json`：范围、分页完成状态、四大满贯、交叉检查及边界。',
             '- `reports/poly-tennis-tags-all.json`：完整观察标签及字典中的名称候选，保留未确认项。',
             '- `reports/poly-tennis-series-all.json`：全量系列字典中识别出的网球系列。',
             '- `reports/poly-tennis-competitions-all.json`：具体赛事原始名称、来源、入口、示例事件、阶段线索。',
             '- `reports/poly-tennis-quarantine.json`：根标签误标的其他运动事件，保留证据但不纳入网球枚举。', '',
             '```bash', 'python3 enumerate_poly_tennis.py --output data/market-audit/2026-10-26/enumeration --cross-checks',
             'python3 build_poly_enumeration.py --input data/market-audit/2026-10-26/enumeration', '```', '',
             '基础扫描器复用本轮压缩缓存；新日期核查应使用新输出目录。补充标签／系列查询的条件均记录在各自 status.json，汇总器读取已保存的补充证据。正式采集使用官方游标分页，不沿用已提示弃用的旧事件 offset 接口。', '',
             '来源：[官方标签接口](https://docs.polymarket.com/api-reference/tags/list-tags)、[官方系列接口](https://docs.polymarket.com/api-reference/series/list-series)、[官方事件游标分页](https://docs.polymarket.com/api-reference/events/list-events-keyset-pagination)。所有枚举数和历史事件来自本项目保存的官方 Gamma 原始响应。', '',
             '## 七、具体赛事原始枚举（完整附录）', '',
             f"共 {summary['competition_labels_unique']} 个不同原始名称，按 sport 与来源展开为 {summary['competition_label_rows']} 行。资格赛、男女组、届次序号和赞助商别名暂保留原样，因此不等于同样数量的官方独立赛事。源字段中少量对阵姓名误填为 league，已标记 league_contains_matchup 待核验，不能自动作为 ForeGate 联赛分类。", '']
    for sport in sorted({r['poly_sport'] for r in leagues}):
        lines += ['### ' + sport, '', table(['原始赛事名称', '识别来源', '事件数', '示例事件 ID', '问题标记'],
                  [[r['league_raw'], r['source'], r['events'], r['example_event_id'], ', '.join(r['issues'])] for r in leagues if r['poly_sport'] == sport]), '']
    lines += ['## 八、完整共现标签与名称候选', '', table(['标签 ID', 'label', 'slug', '目录共现事件数'],
               [[r['id'], r.get('label'), r.get('slug'), r['catalog_events']] for r in tags]), '']
    target = ROOT / 'docs/Poly网球完整分类枚举-2026-10-26.md'
    target.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'data/market-audit/2026-10-26/enumeration')
    args = parser.parse_args()
    print(json.dumps(build(args.input), ensure_ascii=False, indent=2))
