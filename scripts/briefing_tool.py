#!/usr/bin/env python3
"""公开政企简报的离线验证、周期计算、内容质量检查与HTML渲染工具。"""
import argparse
import calendar
import ipaddress
import json
import math
import re
import sys
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

TZ = timezone(timedelta(hours=8), 'Asia/Shanghai')
MAX_BYTES = 256 * 1024
MAX_REGIONS = 30

# 阅读视角：键 → 可读名称。只调整编辑排序与展开深度，不代表地域范围或机构抬头。
AUDIENCE_LABELS = {
    # 通用
    'general': '通用阅读', 'province': '全域阅读', 'regional': '区域机构', 'executive': '管理层',
    # 政府、园区与国资
    'investment_promotion': '招商引资', 'policy_research': '政策研究', 'park_operation': '园区运营',
    'state_owned': '国资国企',
    # 企业
    'corporate_strategy': '企业战略投资', 'business_development': '市场拓展', 'supply_chain': '供应链采购',
    'government_affairs': '政府事务',
    # 研究、咨询与媒体
    'industry_research': '产业研究', 'investment_research': '投资研究', 'consulting': '咨询服务',
    'legal_compliance': '法律合规', 'media': '财经媒体',
    # 金融机构
    'corporate': '公司金融', 'strategic_clients': '战略客户', 'tech_finance': '科技金融', 'inclusive': '普惠金融',
    'institutions': '金融机构', 'transaction_banking': '交易银行', 'bills': '票据业务', 'cross_border': '跨境金融',
    'investment_banking': '投行与债券', 'insurance': '保险机构', 'retail': '零售金融', 'retail_credit': '零售信贷',
    'private_banking': '私人银行', 'wealth': '财富管理', 'planning_finance': '计划财务', 'risk': '风险管理',
    'credit_approval': '授信审批', 'operations': '中后台运营', 'relationship': '一线客户经理',
    # 旧版兼容
    'headquarters': '一般阅读（旧值）', 'regional_branch': '区域阅读（旧值）',
}
AUDIENCES = tuple(AUDIENCE_LABELS)
THEMES = {'classic': '暖纸深红', 'navy': '商务蓝', 'ink': '素墨', 'jade': '青绿'}
LAYOUTS = {'standard': '标准版', 'compact': '速读版', 'memo': '要报版'}
COLOR_SCHEMES = ('auto', 'light')
CHART_KINDS = ('publisher', 'theme', 'region', 'enterprise', 'stage')
REPORT_KINDS = ('daily', 'weekly', 'monthly', 'special')


class ValidationError(ValueError):
    pass


def fail(path, message):
    raise ValidationError(f'{path}: {message}')


def load_json(path):
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            fail('$', 'JSON不允许非有限数值')
        return result

    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                fail('$', 'JSON含重复字段')
            result[key] = value
        return result

    try:
        with open(path, 'rb') as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            fail('$', 'JSON文件超过256KB')
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_float=finite_float,
                          parse_constant=lambda value: fail('$', 'JSON不允许非有限数值'))
    except ValidationError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError):
        fail('$', '无法读取有效UTF-8 JSON文件')


def obj(value, path, required, optional=()):
    if type(value) is not dict:
        fail(path, '必须是对象')
    for key in required:
        if key not in value:
            fail(f'{path}.{key}', '缺少必填字段')
    if set(value) - set(required) - set(optional):
        fail(path, '含未声明字段')
    return value


def text(value, path, maximum=200, empty=False):
    if type(value) is not str:
        fail(path, '必须是字符串')
    if any(unicodedata.category(c) in ('Cc', 'Cs') for c in value):
        fail(path, '字符串含控制字符或无效Unicode字符')
    value = value.strip()
    if len(value) > maximum or (not empty and not value):
        fail(path, f'字符串长度必须为{0 if empty else 1}至{maximum}')
    return value


def array(value, path, maximum=1000):
    if type(value) is not list:
        fail(path, '必须是数组')
    if len(value) > maximum:
        fail(path, '数组超过数量上限')
    return value


def enum(value, path, allowed):
    if type(value) is not str or value not in allowed:
        fail(path, '不是允许的枚举值')
    return value


def integer(value, path, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        fail(path, f'必须是{minimum}至{maximum}的整数')
    return value


def version(data):
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        fail('$.schema_version', '必须是整数1')


def validate_presentation(value, path):
    """版式偏好：配色、版式、深色模式与图表选择；只影响呈现，不改变事实。"""
    obj(value, path, (), ('theme', 'layout', 'color_scheme', 'charts'))
    result = {}
    if 'theme' in value:
        result['theme'] = enum(value['theme'], path + '.theme', tuple(THEMES))
    if 'layout' in value:
        result['layout'] = enum(value['layout'], path + '.layout', tuple(LAYOUTS))
    if 'color_scheme' in value:
        result['color_scheme'] = enum(value['color_scheme'], path + '.color_scheme', COLOR_SCHEMES)
    if 'charts' in value:
        charts = array(value['charts'], path + '.charts', len(CHART_KINDS))
        result['charts'] = [enum(chart, f'{path}.charts[{i}]', CHART_KINDS) for i, chart in enumerate(charts)]
        if len(set(result['charts'])) != len(result['charts']):
            fail(path + '.charts', '图表类型重复')
    return result


def validate_config(data):
    obj(data, '$', ('schema_version', 'audience', 'regions'),
        ('config_name', 'region_label', 'enterprises', 'topics', 'scope_mode', 'timezone', 'history_mode', 'max_items',
         'source_types', 'require_topic_match', 'presentation'))
    version(data)
    result = {'schema_version': 1, 'audience': enum(data['audience'], '$.audience', AUDIENCES)}
    if 'config_name' in data:
        result['config_name'] = text(data['config_name'], '$.config_name', 80)
    if 'region_label' in data:
        result['region_label'] = text(data['region_label'], '$.region_label', 40)
    regions = array(data['regions'], '$.regions', MAX_REGIONS)
    if not regions:
        fail('$.regions', '至少需要一个区域')
    result['regions'] = []
    seen = set()
    for i, region in enumerate(regions):
        p = f'$.regions[{i}]'
        obj(region, p, ('name', 'level'), ('parent',))
        level = enum(region['level'], p + '.level', ('country', 'province', 'city', 'county'))
        if level != 'country' and 'parent' not in region:
            fail(p + '.parent', '缺少必填字段')
        normalized = {'name': text(region['name'], p + '.name'),
                      'parent': text(region.get('parent', ''), p + '.parent', empty=level == 'country'),
                      'level': level}
        key = tuple(normalized.values())
        if key in seen:
            fail(p, '区域重复')
        seen.add(key)
        result['regions'].append(normalized)
    result['enterprises'] = []
    names = set()
    for i, enterprise in enumerate(array(data.get('enterprises', []), '$.enterprises', 100)):
        p = f'$.enterprises[{i}]'
        obj(enterprise, p, ('name',), ('aliases', 'identifier', 'region', 'include_subsidiaries'))
        item = {'name': text(enterprise['name'], p + '.name'), 'aliases': []}
        for j, alias in enumerate(array(enterprise.get('aliases', []), p + '.aliases', 100)):
            item['aliases'].append(text(alias, f'{p}.aliases[{j}]'))
        for name in [item['name']] + item['aliases']:
            if name in names:
                fail(p, '企业名称或别名碰撞')
            names.add(name)
        for field in ('identifier', 'region'):
            if field in enterprise:
                item[field] = text(enterprise[field], p + '.' + field, 64 if field == 'identifier' else 200)
        flag = enterprise.get('include_subsidiaries', False)
        if type(flag) is not bool:
            fail(p + '.include_subsidiaries', '必须是布尔值')
        item['include_subsidiaries'] = flag
        result['enterprises'].append(item)
    result['topics'] = [text(v, f'$.topics[{i}]') for i, v in enumerate(array(data.get('topics', []), '$.topics', 30))]
    if len(set(result['topics'])) != len(result['topics']):
        fail('$.topics', '主题重复')
    for field, default, allowed in (
        ('scope_mode', 'any', ('any', 'all')),
        ('timezone', 'Asia/Shanghai', ('Asia/Shanghai',)),
        ('history_mode', 'aggregate_only', ('aggregate_only', 'backfill_public'))):
        result[field] = enum(data.get(field, default), '$.' + field, allowed)
    if any(region['level'] == 'country' for region in result['regions']):
        if len(result['regions']) > 1:
            fail('$.regions', '全国范围不能与其他地区并列')
        if result['scope_mode'] != 'all' or not (result['topics'] or result['enterprises']):
            fail('$.regions', '全国范围必须使用scope_mode=all并配置至少一个主题或企业，避免无边界采集')
    result['max_items'] = integer(data.get('max_items', 12), '$.max_items', 1, 50)
    source_types = array(data.get('source_types', ['gov', 'enterprise', 'other']), '$.source_types', 3)
    if not source_types:
        fail('$.source_types', '至少选择一种发布主体类别')
    result['source_types'] = [enum(value, f'$.source_types[{i}]', ('gov', 'enterprise', 'other')) for i, value in enumerate(source_types)]
    if len(set(result['source_types'])) != len(result['source_types']):
        fail('$.source_types', '类别重复')
    require_topic = data.get('require_topic_match', False)
    if type(require_topic) is not bool:
        fail('$.require_topic_match', '必须是布尔值')
    if require_topic and not result['topics']:
        fail('$.topics', '只看选定主题时至少需要一个主题')
    result['require_topic_match'] = require_topic
    if 'presentation' in data:
        result['presentation'] = validate_presentation(data['presentation'], '$.presentation')
    return result


def iso_datetime(value, path):
    value = text(value, path, 80)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value):
        fail(path, '必须是带时区的ISO日期时间（含秒）')
    if value[-1] != 'Z' and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        fail(path, '无效时区偏移')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            fail(path, '缺少时区')
        return parsed.astimezone(TZ)
    except (ValueError, OverflowError):
        fail(path, '无效日期时间')


def iso_date(value, path):
    value = text(value, path, 10)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        fail(path, '必须是YYYY-MM-DD日期')
    try:
        return date.fromisoformat(value)
    except ValueError:
        fail(path, '无效日期')


def compute_window(kind, as_of, period=None):
    enum(kind, '$.kind', REPORT_KINDS)
    now = iso_datetime(as_of, '$.as_of')
    today = now.date()
    try:
        if kind == 'daily':
            start_day = iso_date(period, '$.period') if period is not None else today - timedelta(days=1)
            end_day = start_day + timedelta(days=1)
        elif kind == 'weekly':
            if period is None:
                start_day = today - timedelta(days=today.weekday() + 7)
            else:
                if type(period) is not str or not re.fullmatch(r'\d{4}-W\d{2}', period):
                    fail('$.period', '周周期必须是YYYY-Www')
                start_day = date.fromisocalendar(int(period[:4]), int(period[6:]), 1)
            end_day = start_day + timedelta(days=7)
        elif kind == 'monthly':
            if period is None:
                start_day = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            else:
                if type(period) is not str or not re.fullmatch(r'\d{4}-\d{2}', period):
                    fail('$.period', '月周期必须是YYYY-MM')
                start_day = date(int(period[:4]), int(period[5:]), 1)
            end_day = start_day + timedelta(days=calendar.monthrange(start_day.year, start_day.month)[1])
        else:
            if type(period) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}', period):
                fail('$.period', '专题周期必须是YYYY-MM-DD/YYYY-MM-DD（含首尾两日）')
            first, last = period.split('/')
            start_day, last_day = iso_date(first, '$.period'), iso_date(last, '$.period')
            if last_day < start_day:
                fail('$.period', '专题周期结束日不能早于开始日')
            end_day = last_day + timedelta(days=1)
            if (end_day - start_day).days > 366:
                fail('$.period', '专题周期不超过366个自然日')
        start = datetime.combine(start_day, time(), TZ)
        end = datetime.combine(end_day, time(), TZ)
    except (ValueError, OverflowError):
        fail('$.period', '无效周期或日期超出范围')
    if start >= now:
        fail('$.period', '不允许未来或零长度周期')
    return {'start': start.isoformat(), 'end_exclusive': min(end, now).isoformat(),
            'cutoff': now.isoformat(), 'timezone': 'Asia/Shanghai'}


def safe_url(value, path):
    value = text(value, path, 4096)
    if any(c.isspace() for c in value) or '\\' in value:
        fail(path, '链接含不安全字符')
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
        credential_keys = {'token', 'access_token', 'api_key', 'apikey', 'key', 'authorization',
                           'signature', 'sig', 'credential', 'password', 'secret',
                           'x-amz-signature', 'x-amz-credential', 'x-amz-security-token',
                           'x-goog-signature', 'x-goog-credential', 'session_token', 'auth', 'client_secret'}
        for component in (parts.query, parts.fragment, parts.fragment.replace('?', '&')):
            for key, unused in parse_qsl(component, keep_blank_values=True):
                if key.lower() in credential_keys:
                    fail(path, '不允许明显含凭据或签名的链接')
        if parts.scheme not in ('http', 'https') or not host or parts.username is not None or parts.password is not None:
            fail(path, '仅允许无凭据的HTTP/HTTPS来源链接')
        host = host.rstrip('.').lower()
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.lan')) or '.' not in host and ':' not in host:
            fail(path, '不允许本机或内网地址')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ':' in host or not re.fullmatch(r'[a-z0-9.-]+', host) or all(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', part) for part in host.split('.')):
                fail(path, '不允许非规范主机地址')
            labels = host.split('.')
            if any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in labels):
                fail(path, '无效主机名')
        else:
            if not address.is_global or (getattr(address, 'ipv4_mapped', None) is not None and not address.ipv4_mapped.is_global):
                fail(path, '不允许私网或保留IP地址')
        if port is not None and not 1 <= port <= 65535:
            fail(path, '无效端口')
    except ValueError as exc:
        if isinstance(exc, ValidationError):
            raise
        fail(path, '无效来源链接')
    return value


def evidence_refs(value, path, ids, required):
    refs = array(value, path, 1000)
    if required and not refs:
        fail(path, '必须引用本期已核实事项')
    seen = set()
    for i, ref in enumerate(refs):
        ref = text(ref, f'{path}[{i}]', 500)
        if ref not in ids or ref in seen:
            fail(path, '引用不存在或重复的事项ID')
        seen.add(ref)
    return refs


def validate_report(data):
    obj(data, '$', ('schema_version', 'kind', 'title', 'status', 'audience', 'config_summary', 'period', 'coverage', 'items'),
        ('sections', 'summary', 'issue', 'presentation', 'key_figures', 'watchlist'))
    version(data)
    kind = enum(data['kind'], '$.kind', REPORT_KINDS)
    status = enum(data['status'], '$.status', ('formal', 'observation'))
    enum(data['audience'], '$.audience', AUDIENCES)
    for field in ('title', 'config_summary'):
        text(data[field], '$.' + field, 20000)
    if 'issue' in data:
        text(data['issue'], '$.issue', 30)
    if 'presentation' in data:
        validate_presentation(data['presentation'], '$.presentation')
    period = obj(data['period'], '$.period', ('start', 'end_exclusive', 'cutoff'))
    dates = {key: iso_datetime(value, '$.period.' + key) for key, value in period.items()}
    start, end, cutoff = (dates[key] for key in ('start', 'end_exclusive', 'cutoff'))
    if not start < end <= cutoff:
        fail('$.period', '必须满足start < end_exclusive <= cutoff')
    if start.timetz().replace(tzinfo=None) != time():
        fail('$.period.start', '周期必须从北京时间00:00开始')
    try:
        if kind == 'daily':
            full_end = start + timedelta(days=1)
        elif kind == 'weekly':
            if start.weekday() != 0:
                fail('$.period.start', '周报必须从周一开始')
            full_end = start + timedelta(days=7)
        elif kind == 'monthly':
            if start.day != 1:
                fail('$.period.start', '月报必须从每月1日开始')
            full_end = start + timedelta(days=calendar.monthrange(start.year, start.month)[1])
        else:
            full_end = end
    except ValidationError:
        raise
    except (ValueError, OverflowError):
        fail('$.period', '周期超出日期范围')
    if end > full_end:
        fail('$.period.end_exclusive', '超出所选报告类型的周期')
    partial = end < full_end
    if partial and (end != cutoff or status != 'observation'):
        fail('$.period', '部分周期必须截至cutoff并标为观察稿')
    actual_days = (end.date() - start.date()).days + (end.timetz().replace(tzinfo=None) != time())
    if actual_days > 366:
        fail('$.period', '专题周期不超过366个自然日')
    coverage = obj(data['coverage'], '$.coverage', ('expected_days', 'available_days', 'gaps', 'method'), ('highlights',))
    if 'highlights' in coverage:
        for i, value in enumerate(array(coverage['highlights'], '$.coverage.highlights', 3)):
            text(value, f'$.coverage.highlights[{i}]', 500)
    expected = integer(coverage['expected_days'], '$.coverage.expected_days', 1, 366)
    if expected != actual_days:
        fail('$.coverage.expected_days', '必须等于发布周期覆盖的自然日数量')
    available = integer(coverage['available_days'], '$.coverage.available_days', 0, expected)
    gaps = array(coverage['gaps'], '$.coverage.gaps', 366)
    if partial and not gaps:
        fail('$.coverage.gaps', '部分周期必须说明未完成的周期与覆盖局限')
    for i, gap in enumerate(gaps):
        text(gap, f'$.coverage.gaps[{i}]', 2000)
    enum(coverage['method'], '$.coverage.method', ('aggregate_only', 'backfill_public'))
    if status == 'formal' and (gaps or available != expected):
        fail('$.coverage', '正式简报必须覆盖完整且无缺口')
    items = array(data['items'], '$.items', 1000)
    if status == 'formal' and not items:
        fail('$.items', '正式简报至少需要一条已核实事项')
    ids, events = set(), set()
    for i, item in enumerate(items):
        p = f'$.items[{i}]'
        obj(item, p, ('id', 'title', 'summary', 'region', 'enterprise', 'topic', 'published_at', 'event_date', 'sources', 'verification', 'analysis', 'section', 'event_key'),
            ('theme', 'stage', 'publisher_type', 'reader_summary', 'reader_analysis', 'priority'))
        if 'reader_summary' in item:
            text(item['reader_summary'], p + '.reader_summary', 20000)
        if 'reader_analysis' in item:
            text(item['reader_analysis'], p + '.reader_analysis', 20000, empty=True)
        if 'publisher_type' in item:
            enum(item['publisher_type'], p + '.publisher_type', ('gov', 'enterprise', 'other'))
        if 'priority' in item:
            enum(item['priority'], p + '.priority', ('high', 'normal'))
        for key in ('theme', 'stage'):
            if key in item:
                text(item[key], p + '.' + key, 80)
        for key in ('id', 'title', 'summary', 'region', 'enterprise', 'topic', 'analysis', 'section', 'event_key'):
            text(item[key], p + '.' + key, 20000 if key in ('summary', 'analysis') else 500, key in ('enterprise', 'analysis'))
        item_id = item['id'].strip()
        event = item['event_key'].strip()
        if item_id in ids:
            fail(p + '.id', '事项ID重复')
        if event in events:
            fail(p + '.event_key', '事件重复')
        ids.add(item_id)
        events.add(event)
        enum(item['verification'], p + '.verification', ('primary_verified', 'independent_verified'))
        published = iso_datetime(item['published_at'], p + '.published_at')
        if not start <= published < end or published > cutoff:
            fail(p + '.published_at', '事项发布日期不在周期或晚于截止时间')
        if item['event_date'] is not None:
            event_day = iso_date(item['event_date'], p + '.event_date')
            if event_day > cutoff.date():
                fail(p + '.event_date', '事件日期晚于截止时间')
        sources = array(item['sources'], p + '.sources', 100)
        if not sources:
            fail(p + '.sources', '至少需要一个来源')
        source_urls = set()
        matches_publication = False
        for j, source in enumerate(sources):
            q = f'{p}.sources[{j}]'
            obj(source, q, ('name', 'url', 'published_at', 'retrieved_at'))
            text(source['name'], q + '.name', 500)
            source_urls.add(safe_url(source['url'], q + '.url'))
            source_date = iso_datetime(source['published_at'], q + '.published_at')
            matches_publication = matches_publication or source_date == published
            retrieved = iso_datetime(source['retrieved_at'], q + '.retrieved_at')
            if not source_date <= retrieved <= cutoff:
                fail(q, '必须满足来源发布日期 <= 检索日期 <= 截止时间')
        if not matches_publication:
            fail(p + '.published_at', '至少一个来源的原始发布日期必须等于事项发布日期')
        if item['verification'] == 'independent_verified' and len(source_urls) < 2:
            fail(p + '.sources', '独立核实至少需要两个不同来源URL，实际独立性仍须人工核验')
    if 'summary' in data:
        summary = obj(data['summary'], '$.summary', ('text', 'evidence_ids'))
        text(summary['text'], '$.summary.text', 400)
        if not items:
            fail('$.summary.evidence_ids', '内容摘要必须引用本期已核实事项，无事项时省略summary')
        evidence_refs(summary['evidence_ids'], '$.summary.evidence_ids', ids, True)
    if 'key_figures' in data:
        figures = array(data['key_figures'], '$.key_figures', 6)
        if figures and not items:
            fail('$.key_figures', '关键数字必须引用本期已核实事项，无事项时省略')
        for i, figure in enumerate(figures):
            p = f'$.key_figures[{i}]'
            obj(figure, p, ('label', 'value', 'note', 'evidence_ids'))
            text(figure['label'], p + '.label', 30)
            text(figure['value'], p + '.value', 30)
            text(figure['note'], p + '.note', 200)
            evidence_refs(figure['evidence_ids'], p + '.evidence_ids', ids, True)
    if 'watchlist' in data:
        for i, entry in enumerate(array(data['watchlist'], '$.watchlist', 12)):
            p = f'$.watchlist[{i}]'
            obj(entry, p, ('text',), ('evidence_ids',))
            text(entry['text'], p + '.text', 300)
            evidence_refs(entry.get('evidence_ids', []), p + '.evidence_ids', ids, False)
    sections = array(data.get('sections', []), '$.sections', 100)
    for i, section in enumerate(sections):
        p = f'$.sections[{i}]'
        obj(section, p, ('heading', 'body', 'evidence_ids'))
        text(section['heading'], p + '.heading', 500)
        text(section['body'], p + '.body', 20000)
        evidence = array(section['evidence_ids'], p + '.evidence_ids', 1000)
        if status == 'formal' and not evidence:
            fail(p + '.evidence_ids', '正式专题必须引用证据')
        for j, evidence_id in enumerate(evidence):
            evidence_id = text(evidence_id, f'{p}.evidence_ids[{j}]', 500)
            if evidence_id not in ids:
                fail(p + '.evidence_ids', '引用了不存在的事项ID')
    return data


# ---------------------------------------------------------------------------
# 内容质量检查：只做可机器判断的写作规范提示，不判断真实性、独立性或主题语义。

COUNT_SUMMARY = re.compile(r'(本期|本周|本月|今日|昨日)(共|合计)?(收录|核实|整理|发布|编制)?\s*\d+\s*(条|则)|(政府|企业|其他)(资讯|发布|来源)\s*\d+\s*条')
PROCESS_NOTES = ('编码占位', '占位符', '证据根', '抓取', '爬取', '采集脚本', '检索时点', '非承载网站', '精确分配', '已标注', 'retrieved_at', 'placeholder')
CREDIT_MARKETING = ('授信额度', '可授信', '放款', '贷款需求', '融资需求旺盛', '营销机会', '营销建议', '营销切入', '抢占客户', '拜访客户', '上门拜访', '客户经理可')
INVESTMENT_ADVICE = ('建议买入', '建议增持', '建议卖出', '目标价', '推荐买入', '值得投资', '稳赚', '收益承诺')
HYPE = ('重磅', '炸裂', '震撼', '史上最', '全面爆发', '爆发式', '王炸', '必将', '颠覆', '利好', '利空', '狂飙', '血洗')


def lint_report(data):
    """返回内容质量提示：error须改正，warning建议改正，info供编辑参考。"""
    validate_report(data)
    findings = []

    def add(level, path, message):
        findings.append({'level': level, 'path': path, 'message': message})

    def scan(value, path, reader_facing=True):
        if not value:
            return
        for word in CREDIT_MARKETING:
            if word in value:
                add('error', path, f'含“{word}”：不得从公开信息推断贷款需求、授信或营销安排')
        for word in INVESTMENT_ADVICE:
            if word in value:
                add('error', path, f'含“{word}”：不得给出投资建议或收益判断')
        for word in HYPE:
            if word in value:
                add('warning', path, f'含“{word}”：避免渲染性或带交易含义的措辞')
        if reader_facing:
            for word in PROCESS_NOTES:
                if word in value:
                    add('error', path, f'读者正文含编制说明“{word}”：改写reader_summary/reader_analysis，原说明留在summary/analysis')

    items = data['items']
    kind = data['kind']
    summary = data.get('summary')
    if items and not summary:
        add('warning', '$.summary', '有已核实事项但未编制一句话速览')
    if summary:
        value = summary['text'].strip()
        if COUNT_SUMMARY.search(value):
            add('error', '$.summary.text', '速览不得以条数或来源构成充当摘要，应写具体主体、变化与状态')
        if len(value) < 40 or len(value) > 160:
            add('warning', '$.summary.text', f'速览{len(value)}字，建议60至140字')
        elif len(value) < 60 or len(value) > 140:
            add('info', '$.summary.text', f'速览{len(value)}字，常规区间为60至140字')
        scan(value, '$.summary.text')
    titles = {}
    themes = set()
    for i, item in enumerate(items):
        p = f'$.items[{i}]'
        title = item['title'].strip()
        if len(title) > 40:
            add('warning', p + '.title', f'标题{len(title)}字，建议不超过40字：主体+动作+对象+状态')
        if '!' in title or '！' in title:
            add('warning', p + '.title', '标题不使用感叹号')
        if title in titles:
            add('warning', p + '.title', f'与{titles[title]}标题重复，确认是否同一事件应合并')
        titles.setdefault(title, p)
        missing = [key for key in ('theme', 'stage', 'publisher_type') if key not in item]
        if missing:
            add('warning', p, '缺少分类字段：' + '、'.join(missing) + '；新编报告应逐条填齐')
        themes.add(item.get('theme', '').strip() or '未分类')
        if 'reader_summary' in item:
            scan(item['reader_summary'], p + '.reader_summary')
        else:
            scan(item['summary'], p + '.summary', reader_facing=False)
            if any(word in item['summary'] for word in PROCESS_NOTES):
                add('warning', p + '.summary', '采集摘要含技术说明且未编制reader_summary，读者正文会直接显示这些说明')
            elif len(item['summary']) > 300:
                add('info', p + '.summary', '采集摘要较长，建议编制80至200字的reader_summary')
        if 'reader_analysis' in item:
            scan(item['reader_analysis'], p + '.reader_analysis')
        else:
            scan(item['analysis'], p + '.analysis', reader_facing=False)
        if item['event_date'] and item['event_date'] > item['published_at'][:10]:
            add('info', p + '.event_date', '事件日晚于发布日：确认是否为计划里程碑，计划事项应写入正文并标“计划”')
    if len(items) >= 6 and len(themes) > len(items) * 0.7:
        add('warning', '$.items', f'{len(items)}条事项分为{len(themes)}个主题，主题过碎；建议按主题词表归并')
    for i, section in enumerate(data.get('sections', [])):
        scan(section['body'], f'$.sections[{i}].body')
        scan(section['heading'], f'$.sections[{i}].heading')
    for i, figure in enumerate(data.get('key_figures', [])):
        scan(figure['note'], f'$.key_figures[{i}].note')
    for i, entry in enumerate(data.get('watchlist', [])):
        scan(entry['text'], f'$.watchlist[{i}].text')
    if kind in ('weekly', 'monthly', 'special') and items and not data.get('sections'):
        add('warning', '$.sections', '周报、月报和专题简报应有周期信号或专题分析')
    if kind == 'monthly' and len(data.get('sections', [])) > 4:
        add('info', '$.sections', '月报专题通常2至3个，过多会稀释重点')
    if data['status'] == 'observation' and data['coverage']['gaps'] and not data['coverage'].get('highlights'):
        add('info', '$.coverage.highlights', '观察稿建议用highlights浓缩首屏最重要的覆盖限制')
    counts = {level: sum(1 for f in findings if f['level'] == level) for level in ('error', 'warning', 'info')}
    score = max(0, 100 - 15 * counts['error'] - 5 * counts['warning'] - counts['info'])
    return {'score': score, 'errors': counts['error'], 'warnings': counts['warning'], 'infos': counts['info'], 'findings': findings}


def resolve_presentation(data, theme=None, layout=None, color_scheme=None):
    result = {'theme': 'classic', 'layout': 'standard', 'color_scheme': 'auto'}
    result.update(data.get('presentation', {}))
    for key, value, allowed in (('theme', theme, THEMES), ('layout', layout, LAYOUTS), ('color_scheme', color_scheme, COLOR_SCHEMES)):
        if value is not None:
            result[key] = enum(value, '$.presentation.' + key, tuple(allowed))
    return result


def render_report(data, theme=None, layout=None, color_scheme=None):
    """结构校验后交给自包含的统一阅读模板；不推断摘要或新闻事实。"""
    validate_report(data)
    presentation = resolve_presentation(data, theme, layout, color_scheme)
    import importlib.util
    from pathlib import Path
    design_path = Path(__file__).with_name('report_design.py')
    spec = importlib.util.spec_from_file_location('briefing_report_design', design_path)
    design = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(design)
    return design.render_report(data, presentation, AUDIENCE_LABELS[data['audience']])


def main(argv=None):
    parser = argparse.ArgumentParser(description='公开简报离线辅助工具')
    sub = parser.add_subparsers(dest='command', required=True)
    validate = sub.add_parser('validate-config')
    validate.add_argument('path')
    window = sub.add_parser('window')
    window.add_argument('--kind', required=True, choices=REPORT_KINDS)
    window.add_argument('--as-of', required=True)
    window.add_argument('--period', help='daily: YYYY-MM-DD；weekly: YYYY-Www；monthly: YYYY-MM；special: YYYY-MM-DD/YYYY-MM-DD')
    render = sub.add_parser('render')
    render.add_argument('--data', required=True)
    render.add_argument('--out', required=True)
    render.add_argument('--theme', choices=tuple(THEMES))
    render.add_argument('--layout', choices=tuple(LAYOUTS))
    render.add_argument('--color-scheme', choices=COLOR_SCHEMES)
    lint = sub.add_parser('lint')
    lint.add_argument('--data', required=True)
    lint.add_argument('--strict', action='store_true', help='有warning时也返回1')
    sub.add_parser('options')
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate-config':
            result = validate_config(load_json(args.path))
        elif args.command == 'window':
            result = compute_window(args.kind, args.as_of, args.period)
        elif args.command == 'options':
            result = {'kinds': list(REPORT_KINDS), 'themes': THEMES, 'layouts': LAYOUTS,
                      'color_schemes': list(COLOR_SCHEMES), 'charts': list(CHART_KINDS), 'audiences': AUDIENCE_LABELS}
        elif args.command == 'lint':
            result = lint_report(load_json(args.data))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result['errors'] or (args.strict and result['warnings']) else 0
        else:
            output = render_report(load_json(args.data), args.theme, args.layout, args.color_scheme)
            try:
                with open(args.out, 'x', encoding='utf-8', newline='\n') as target:
                    target.write(output)
            except FileExistsError:
                fail('$.out', '输出路径已存在，禁止覆盖')
            except OSError:
                fail('$.out', '无法创建输出文件')
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValidationError, RecursionError) as exc:
        print(str(exc) if isinstance(exc, ValidationError) else '$: JSON嵌套过深', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
