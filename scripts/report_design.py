"""自包含资讯阅读页；输入数据由调用方验证。"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path


def esc(value):
    return escape(str(value), quote=True)


def date(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=8)))


def links(ids, anchors):
    return ' '.join('<a href="#' + esc(anchors[value.strip()]) + '" aria-label="查看关联事项' + esc(anchors[value.strip()].split('-')[-1]) + '">[' + esc(anchors[value.strip()].split('-')[-1]) + ']</a>' for value in ids if value.strip() in anchors)


def category(item):
    return item['section'].split('·', 1)[0].strip()


def charts(items):
    publisher_labels = {'gov': '政府资讯', 'enterprise': '企业资讯', 'other': '其他来源'}
    counts = Counter(publisher_labels.get(item['publisher_type'], '其他来源') if 'publisher_type' in item else category(item) for item in items)
    themes = Counter(item.get('theme', '').strip() or '未分类' for item in items)
    palette = ('#873b39', '#c68c69', '#6a7c75', '#a09881', '#706b86', '#b98891')
    parts = ['<section class="dashboard" aria-label="本期样本分布">']
    parts.append('<figure class="chart"><figcaption><span class="kicker">来源构成</span><h2>本期发布来源<span class="unit">条</span></h2></figcaption><div class="composition">')
    if len(counts) > 1:
        offset = 0
        parts.append('<svg viewBox="0 0 144 144" role="img" aria-label="' + esc('来源分类事项构成：' + '；'.join(f'{k}{v}条' for k, v in counts.items())) + '"><circle cx="72" cy="72" r="52" fill="none" stroke="#ede6dd" stroke-width="18"/>')
        for n, (name, value) in enumerate(counts.items()):
            share = value / len(items) * 100
            parts.append('<circle cx="72" cy="72" r="52" pathLength="100" fill="none" stroke="' + palette[n % len(palette)] + '" stroke-width="18" stroke-dasharray="' + esc(f'{share:.8f} {100-share:.8f}') + '" stroke-dashoffset="' + esc(f'{-offset:.8f}') + '" transform="rotate(-90 72 72)"/>')
            offset += share
        parts.append('<text x="72" y="72" text-anchor="middle" class="svg-number">' + str(len(items)) + '</text><text x="72" y="91" text-anchor="middle" class="svg-label">条事项</text></svg>')
    else:
        parts.append('<div class="single-number">' + str(len(items)) + '<small>条事项</small></div>')
    parts.append('<ul class="legend">')
    for n, (name, value) in enumerate(counts.items()):
        parts.append('<li><i style="background:' + palette[n % len(palette)] + '"></i><span>' + esc(name) + '</span><b>' + str(value) + '</b></li>')
    parts.append('</ul></div></figure>')
    if themes:
        total = sum(themes.values())
        ranked = themes.most_common()
        classified = [(name, value) for name, value in ranked if name != '未分类']
        missing = [('未分类', themes['未分类'])] if themes.get('未分类') else []
        limit = 4 if missing else 5
        if len(classified) > limit:
            shown = classified[:limit - 1] + [('其他主题', sum(value for _, value in classified[limit - 1:]))] + missing
        else:
            shown = classified + missing
        description = '主题事项数：' + '；'.join(name + str(value) + '条' for name, value in shown)
        parts.append('<figure class="chart"><figcaption><span class="kicker">内容主题</span><h2>本期关注主题<span class="unit">条</span></h2></figcaption><svg class="theme-map" viewBox="0 0 400 160" preserveAspectRatio="none" role="img" aria-label="' + esc(description) + '">')
        remaining, x, y, width, height = total, 0.0, 0.0, 400.0, 160.0
        for n, (name, value) in enumerate(shown):
            fraction = value / remaining
            if width >= height:
                tile_width, tile_height = width * fraction, height
            else:
                tile_width, tile_height = width, height * fraction
            parts.append('<rect x="' + esc(f'{x:.8f}') + '" y="' + esc(f'{y:.8f}') + '" width="' + esc(f'{tile_width:.8f}') + '" height="' + esc(f'{tile_height:.8f}') + '" fill="' + palette[n % len(palette)] + '"><title>' + esc(name) + '：' + str(value) + '条</title></rect>')
            if width >= height:
                x += tile_width
                width -= tile_width
            else:
                y += tile_height
                height -= tile_height
            remaining -= value
        parts.append('</svg><ul class="legend theme-legend">')
        for n, (name, value) in enumerate(shown):
            parts.append('<li><i style="background:' + palette[n % len(palette)] + '"></i><span>' + esc(name) + '</span><b>' + str(value) + '</b></li>')
        parts.append('</ul>')
        if len(ranked) > 5:
            parts.append('<details class="theme-list"><summary>完整主题清单（' + str(len(ranked)) + '类）</summary><ul>' + ''.join('<li>' + esc(name) + '：' + str(value) + '条</li>' for name, value in ranked) + '</ul></details>')
        parts.append('</figure>')
    parts.append('</section>')
    return ''.join(parts)


def render_report(data):
    css = (Path(__file__).resolve().parent.parent / 'assets' / 'report.css').read_text(encoding='utf-8')
    items, period, coverage = data['items'], data['period'], data['coverage']
    anchors = {item['id'].strip(): 'item-' + str(i + 1) for i, item in enumerate(items)}
    cutoff, start = date(period['cutoff']), date(period['start'])
    last = date(period['end_exclusive']) - timedelta(seconds=1)
    title = data['title'].split('｜', 1)
    dateline = cutoff.strftime('%Y年%m月%d日') if data['kind'] == 'daily' else start.strftime('%Y年%m月%d日') + '—' + last.strftime('%m月%d日')
    label = {'daily': '每日观察', 'weekly': '周度观察', 'monthly': '月度观察'}.get(data['kind'], '资讯观察')
    end = date(period['end_exclusive'])
    midnight = start.hour == start.minute == start.second == 0
    if data['kind'] == 'weekly' and (start.weekday() != 0 or not midnight or end - start != timedelta(days=7) or cutoff < end):
        label = '部分周报'
    if data['kind'] == 'monthly':
        next_month = start.replace(year=start.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) if start.month == 12 else start.replace(month=start.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.day != 1 or not midnight or end != next_month or cutoff < end:
            label = '部分月报'
    parts = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">', '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">', '<title>' + esc(data['title']) + '</title><style>' + css + '</style></head><body><main class="page"><header class="mast"><p class="series">公开资讯 · ' + esc(label) + '</p><h1>' + esc(title[0].strip()) + '</h1>']
    if len(title) > 1 and not any(char.isdigit() for char in title[1]):
        parts.append('<p class="subtitle">' + esc(title[1].strip()) + '</p>')
    parts.append('<div class="dateline"><span>' + esc(dateline) + '</span><span class="status">' + ('正式简报' if data['status'] == 'formal' else '观察稿') + '</span><span>截止 ' + esc(cutoff.strftime('%m-%d %H:%M')) + ' · 北京时间</span></div></header>')
    parts.append('<section class="scope" aria-label="实际编制范围"><p>' + esc(data['config_summary']) + '</p></section>')
    coverage_highlights = coverage.get('highlights') or coverage['gaps'][:2]
    if coverage_highlights:
        parts.append('<section class="coverage-gaps" aria-label="本期阅读提示"><p>' + esc(' '.join(coverage_highlights)) + '</p></section>')
    if items:
        parts.append(charts(items))
        summary = data.get('summary') or {}
        parts.append('<section class="glance" id="glance"><h2>一句话速览</h2><p>' + esc(summary.get('text') or '内容摘要尚未编制，请查看已核实事项。') + '</p>')
        if summary.get('evidence_ids'):
            parts.append('<div class="related">关联事项 ' + links(summary['evidence_ids'], anchors) + '</div>')
        parts.append('</section>')
    else:
        parts.append('<section class="empty"><h2>本期暂无已核实事项</h2><p>现有材料不足以形成内容摘要或分布图，不能据此判断没有事件。</p></section>')
    groups = {}
    for item in items:
        group = category(item)
        subgroup = item['section'].split('·', 1)[1].strip() if '·' in item['section'] else '已核实事项'
        groups.setdefault(group, {}).setdefault(subgroup, []).append(item)
    for group, subgroups in groups.items():
        parts.append('<section class="source-section"><div class="section-heading"><span class="kicker">公开事项</span><h2>' + esc(group) + '</h2></div>')
        for subgroup, entries in subgroups.items():
            parts.append('<section class="subgroup"><h3 class="subgroup-title">' + esc(subgroup) + '</h3><div class="item-grid">')
            for item in entries:
                verified = '一手来源已核实' if item['verification'] == 'primary_verified' else '独立来源已核实'
                parts.append('<article class="item" id="' + anchors[item['id'].strip()] + '"><div class="eyebrow"><span>' + esc(item['region']) + '</span><span>发布 ' + esc(date(item['published_at']).strftime('%Y-%m-%d')) + '</span></div><h4>' + esc(item['title']) + '</h4><h5 class="facts-label">公开事实</h5><p class="fact">' + esc(item.get('reader_summary') or item['summary']) + '</p>')
                reader_analysis = item.get('reader_analysis', item['analysis'])
                if reader_analysis:
                    parts.append('<div class="analysis"><h5>研究关注</h5><p>' + esc(reader_analysis) + '</p></div>')
                tags = [('企业', item['enterprise']), ('议题', item['topic']), ('主题', item.get('theme', '')), ('阶段', item.get('stage', ''))]
                parts.append('<dl class="metadata">' + ''.join('<div><dt>' + label + '</dt><dd>' + esc(value) + '</dd></div>' for label, value in tags if value) + '<div><dt>事件日期</dt><dd>' + esc(item['event_date'] or '未披露') + '</dd></div></dl><div class="sources"><span class="verified">' + verified + '</span>')
                for source in item['sources']:
                    parts.append('<p><a href="' + esc(source['url']) + '" rel="noopener noreferrer">' + esc(source['name']) + '</a><span>发布 ' + esc(date(source['published_at']).strftime('%Y-%m-%d')) + '</span></p>')
                parts.append('</div></article>')
            parts.append('</div></section>')
        parts.append('</section>')
    if data.get('sections'):
        parts.append('<section class="features"><div class="section-heading"><span class="kicker">' + esc(label) + '</span><h2>专题分析</h2></div><div class="feature-grid">')
        for section in data['sections']:
            parts.append('<article class="feature"><h3>' + esc(section['heading']) + '</h3><p>' + esc(section['body']) + '</p>')
            if section.get('evidence_ids'):
                parts.append('<div class="related">关联证据 ' + links(section['evidence_ids'], anchors) + '</div>')
            parts.append('</article>')
        parts.append('</div></section>')
    parts.append('<section class="appendix"><details><summary>完整来源与核验记录</summary><div class="details-body">')
    for item in items:
        parts.append('<section class="evidence-record"><h3><a href="#' + anchors[item['id'].strip()] + '">' + esc(item['title']) + '</a></h3><p>事项ID：' + esc(item['id']) + '<br>核验标记：' + esc(item['verification']) + '<br>事项发布：' + esc(item['published_at']) + '<br>事件日期：' + esc(item['event_date'] or '未披露') + '</p>')
        parts.append('<p>完整采集摘要：' + esc(item['summary']) + '</p><p>分析与核验说明：' + esc(item['analysis']) + '</p><ol>')
        for source in item['sources']:
            parts.append('<li><a href="' + esc(source['url']) + '" rel="noopener noreferrer">' + esc(source['name']) + '</a><p>原文：' + esc(source['url']) + '<br>发布：' + esc(source['published_at']) + '<br>检索：' + esc(source['retrieved_at']) + '</p></li>')
        parts.append('</ol></section>')
    parts.append('</div></details><details id="run-notes"><summary>编制范围、覆盖缺口与运行记录</summary><div class="details-body"><p>完整标题：' + esc(data['title']) + '<br>编制范围：' + esc(data['config_summary']) + '<br>受众配置：' + esc(data['audience']) + '<br>时区：Asia/Shanghai</p><p>周期起点：' + esc(period['start']) + '<br>周期终点（不含）：' + esc(period['end_exclusive']) + '<br>信息截止：' + esc(period['cutoff']) + '<br>日期覆盖：' + esc(coverage['available_days']) + '/' + esc(coverage['expected_days']) + ' 天<br>资料策略：' + esc('仅汇总已有记录' if coverage['method'] == 'aggregate_only' else '补采公开历史资料') + '</p>')
    if coverage['gaps']:
        parts.append('<h3>覆盖缺口</h3><ul>' + ''.join('<li>' + esc(gap) + '</li>' for gap in coverage['gaps']) + '</ul>')
    parts.append('</div></details></section><footer><p>公开信息整理 · 请以原始披露为准</p><p>本报告基于公开信息整理，仅供参阅交流，不构成投资建议、授信审批意见或对任何主体的信用保证。信息可能存在披露滞后和检索遗漏，重要事项请核对原始来源。</p></footer></main></body></html>')
    return ''.join(parts)
