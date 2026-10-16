#!/usr/bin/env python3
"""公开企业简报的离线验证、周期计算与HTML渲染工具。"""
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
AUDIENCES = ('province', 'regional', 'headquarters', 'regional_branch', 'executive', 'corporate',
             'strategic_clients', 'tech_finance', 'inclusive', 'institutions', 'transaction_banking',
             'bills', 'cross_border', 'retail', 'retail_credit', 'private_banking', 'wealth',
             'planning_finance', 'risk', 'credit_approval', 'operations', 'relationship')


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


def validate_config(data):
    obj(data, '$', ('schema_version', 'audience', 'regions'),
        ('config_name', 'enterprises', 'topics', 'scope_mode', 'timezone', 'history_mode', 'max_items', 'source_types', 'require_topic_match'))
    version(data)
    result = {'schema_version': 1, 'audience': enum(data['audience'], '$.audience', AUDIENCES)}
    if 'config_name' in data:
        result['config_name'] = text(data['config_name'], '$.config_name', 80)
    regions = array(data['regions'], '$.regions', 20)
    if not regions:
        fail('$.regions', '至少需要一个区域')
    result['regions'] = []
    seen = set()
    for i, region in enumerate(regions):
        p = f'$.regions[{i}]'
        obj(region, p, ('name', 'parent', 'level'))
        normalized = {'name': text(region['name'], p + '.name'),
                      'parent': text(region['parent'], p + '.parent'),
                      'level': enum(region['level'], p + '.level', ('province', 'city', 'county'))}
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
    enum(kind, '$.kind', ('daily', 'weekly', 'monthly'))
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
        else:
            if period is None:
                start_day = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            else:
                if type(period) is not str or not re.fullmatch(r'\d{4}-\d{2}', period):
                    fail('$.period', '月周期必须是YYYY-MM')
                start_day = date(int(period[:4]), int(period[5:]), 1)
            end_day = start_day + timedelta(days=calendar.monthrange(start_day.year, start_day.month)[1])
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


def validate_report(data):
    obj(data, '$', ('schema_version', 'kind', 'title', 'status', 'audience', 'config_summary', 'period', 'coverage', 'items'), ('sections', 'summary'))
    version(data)
    kind = enum(data['kind'], '$.kind', ('daily', 'weekly', 'monthly'))
    status = enum(data['status'], '$.status', ('formal', 'observation'))
    enum(data['audience'], '$.audience', AUDIENCES)
    for field in ('title', 'config_summary'):
        text(data[field], '$.' + field, 20000)
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
        else:
            if start.day != 1:
                fail('$.period.start', '月报必须从每月1日开始')
            full_end = start + timedelta(days=calendar.monthrange(start.year, start.month)[1])
    except ValidationError:
        raise
    except (ValueError, OverflowError):
        fail('$.period', '周期超出日期范围')
    if end > full_end:
        fail('$.period.end_exclusive', '超出所选报告类型的周期')
    partial = end < full_end
    if partial and (end != cutoff or status != 'observation'):
        fail('$.period', '部分周期必须截至cutoff并标为观察稿')
    coverage = obj(data['coverage'], '$.coverage', ('expected_days', 'available_days', 'gaps', 'method'), ('highlights',))
    if 'highlights' in coverage:
        for i, value in enumerate(array(coverage['highlights'], '$.coverage.highlights', 3)):
            text(value, f'$.coverage.highlights[{i}]', 500)
    expected = integer(coverage['expected_days'], '$.coverage.expected_days', 1, 366)
    actual_days = (end.date() - start.date()).days + (end.timetz().replace(tzinfo=None) != time())
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
        obj(item, p, ('id', 'title', 'summary', 'region', 'enterprise', 'topic', 'published_at', 'event_date', 'sources', 'verification', 'analysis', 'section', 'event_key'), ('theme', 'stage', 'publisher_type', 'reader_summary', 'reader_analysis'))
        if 'reader_summary' in item:
            text(item['reader_summary'], p + '.reader_summary', 20000)
        if 'reader_analysis' in item:
            text(item['reader_analysis'], p + '.reader_analysis', 20000, empty=True)
        if 'publisher_type' in item:
            enum(item['publisher_type'], p + '.publisher_type', ('gov', 'enterprise', 'other'))
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
        refs = array(summary['evidence_ids'], '$.summary.evidence_ids', 1000)
        if not items or not refs:
            fail('$.summary.evidence_ids', '内容摘要必须引用本期已核实事项，无事项时省略summary')
        seen_refs = set()
        for i, ref in enumerate(refs):
            ref = text(ref, f'$.summary.evidence_ids[{i}]', 500)
            if ref not in ids or ref in seen_refs:
                fail('$.summary.evidence_ids', '摘要引用不存在或重复的事项ID')
            seen_refs.add(ref)
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


def render_report(data):
    """结构校验后交给自包含的统一阅读模板；不推断摘要或新闻事实。"""
    validate_report(data)
    import importlib.util
    from pathlib import Path
    design_path = Path(__file__).with_name('report_design.py')
    spec = importlib.util.spec_from_file_location('briefing_report_design', design_path)
    design = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(design)
    return design.render_report(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description='公开简报离线辅助工具')
    sub = parser.add_subparsers(dest='command', required=True)
    validate = sub.add_parser('validate-config')
    validate.add_argument('path')
    window = sub.add_parser('window')
    window.add_argument('--kind', required=True, choices=('daily', 'weekly', 'monthly'))
    window.add_argument('--as-of', required=True)
    window.add_argument('--period')
    render = sub.add_parser('render')
    render.add_argument('--data', required=True)
    render.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate-config':
            result = validate_config(load_json(args.path))
        elif args.command == 'window':
            result = compute_window(args.kind, args.as_of, args.period)
        else:
            output = render_report(load_json(args.data))
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
