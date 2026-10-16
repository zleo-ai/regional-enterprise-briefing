"""离线简报辅助工具的标准库回归测试。"""
import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import unittest
import re
from html.parser import HTMLParser
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'briefing_tool.py'
SPEC = importlib.util.spec_from_file_location('briefing_tool', SCRIPT)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def config():
    return {'schema_version': 1, 'audience': 'regional_branch',
            'regions': [{'name': '苏州市', 'parent': '江苏省', 'level': 'city'}]}


def report():
    return {'schema_version': 1, 'kind': 'daily', 'title': '公开简报', 'status': 'formal',
            'audience': 'headquarters', 'config_summary': '苏州市公开事项',
            'period': {'start': '2024-02-29T00:00:00+08:00', 'end_exclusive': '2024-03-01T00:00:00+08:00', 'cutoff': '2024-03-01T00:00:00+08:00'},
            'coverage': {'expected_days': 1, 'available_days': 1, 'gaps': [], 'method': 'aggregate_only'},
            'items': [{'id': 'item-1', 'title': '示例公告', 'summary': '公开事实', 'region': '苏州市', 'enterprise': '', 'topic': '项目进展',
                       'published_at': '2024-02-29T10:00:00+08:00', 'event_date': '2024-02-29',
                       'sources': [{'name': '公开来源', 'url': 'https://example.com/article?a=1&b=2',
                                    'published_at': '2024-02-29T10:00:00+08:00', 'retrieved_at': '2024-02-29T12:00:00+08:00'}],
                       'verification': 'primary_verified', 'analysis': '分析结论', 'section': '公开事项', 'event_key': 'event-1'}]}


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        value = tool.validate_config(config())
        self.assertEqual(value['max_items'], 12)
        self.assertEqual(value['timezone'], 'Asia/Shanghai')
        self.assertEqual(value['enterprises'], [])
        self.assertEqual(value['topics'], [])

    def test_trim(self):
        value = config()
        value['config_name'] = ' 测试 '
        self.assertEqual(tool.validate_config(value)['config_name'], '测试')

    def test_missing_field_path(self):
        value = config()
        del value['audience']
        with self.assertRaisesRegex(tool.ValidationError, r'\$\.audience'):
            tool.validate_config(value)

    def test_unknown_top_level(self):
        value = config()
        value['secret'] = 'sensitive'
        with self.assertRaises(tool.ValidationError) as ctx:
            tool.validate_config(value)
        self.assertNotIn('sensitive', str(ctx.exception))

    def test_unknown_nested(self):
        value = config()
        value['regions'][0]['extra'] = 1
        with self.assertRaisesRegex(tool.ValidationError, r'\$\.regions\[0\]'):
            tool.validate_config(value)

    def test_bool_version_and_count(self):
        for field in ('schema_version', 'max_items'):
            value = config()
            value[field] = True
            with self.subTest(field=field), self.assertRaises(tool.ValidationError):
                tool.validate_config(value)

    def test_regions_empty_or_duplicate(self):
        for regions in ([], config()['regions'] * 2):
            value = config()
            value['regions'] = regions
            with self.subTest(regions=regions), self.assertRaises(tool.ValidationError):
                tool.validate_config(value)

    def test_limits(self):
        for field, value in [('regions', config()['regions'] * 21), ('topics', ['a'] * 31), ('enterprises', [{'name': str(i)} for i in range(101)]), ('max_items', 51), ('config_name', 'a' * 81)]:
            data = config()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(tool.ValidationError):
                tool.validate_config(data)

    def test_strict_types(self):
        for field, value in [('topics', 'text'), ('regions', {}), ('audience', 1), ('max_items', 1.0)]:
            data = config()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(tool.ValidationError):
                tool.validate_config(data)

    def test_text_controls_and_empty(self):
        for name in ('  ', 'a\nb', 'a\x00b', 'a\x7fb', 'a' * 201):
            value = config()
            value['regions'][0]['name'] = name
            with self.subTest(name=name), self.assertRaises(tool.ValidationError):
                tool.validate_config(value)

    def test_natural_text_preserved(self):
        value = config()
        value['topics'] = ['研究<script>alert(1)</script>技术']
        self.assertEqual(tool.validate_config(value)['topics'], value['topics'])

    def test_enterprise_defaults_and_identifier(self):
        value = config()
        value['enterprises'] = [{'name': '示例企业', 'identifier': 'x' * 64}]
        normalized = tool.validate_config(value)['enterprises'][0]
        self.assertFalse(normalized['include_subsidiaries'])
        self.assertEqual(normalized['aliases'], [])
        value['enterprises'][0]['identifier'] += 'x'
        with self.assertRaises(tool.ValidationError):
            tool.validate_config(value)

    def test_alias_collision(self):
        value = config()
        value['enterprises'] = [{'name': '甲', 'aliases': ['乙']}, {'name': '乙'}]
        with self.assertRaises(tool.ValidationError):
            tool.validate_config(value)

    def test_enterprise_bool_and_unknown(self):
        for field, content in [('include_subsidiaries', 1), ('aliases', '别名'), ('private_data', 'secret')]:
            value = config()
            value['enterprises'] = [{'name': '甲', field: content}]
            with self.subTest(field=field), self.assertRaises(tool.ValidationError):
                tool.validate_config(value)

    def test_duplicate_topics(self):
        value = config()
        value['topics'] = ['项目进展', ' 项目进展 ']
        with self.assertRaisesRegex(tool.ValidationError, r'\$\.topics'):
            tool.validate_config(value)

    def test_float_version(self):
        value = config()
        value['schema_version'] = 1.0
        with self.assertRaisesRegex(tool.ValidationError, r'\$\.schema_version'):
            tool.validate_config(value)
        data = report()
        data['schema_version'] = 1.0
        with self.assertRaisesRegex(tool.ValidationError, r'\$\.schema_version'):
            tool.render_report(data)

    def test_invalid_enums(self):
        for field in ('timezone', 'audience', 'scope_mode', 'history_mode'):
            value = config()
            value[field] = 'invalid'
            with self.subTest(field=field), self.assertRaises(tool.ValidationError):
                tool.validate_config(value)


class NewConfigurationTests(unittest.TestCase):
    def test_all_reading_views_flow_through_config_and_report(self):
        for audience in tool.AUDIENCES:
            selected = config()
            selected['audience'] = audience
            normalized = tool.validate_config(selected)
            data = report()
            data['audience'] = normalized['audience']
            with self.subTest(audience=audience):
                self.assertIn('苏州市公开事项', tool.render_report(data))

    def test_source_filters_are_explicit_and_strict(self):
        value = config()
        self.assertEqual(tool.validate_config(value)['source_types'], ['gov', 'enterprise', 'other'])
        for content in ([], ['gov', 'gov'], ['internal'], 'gov', [True]):
            value['source_types'] = content
            with self.subTest(content=content), self.assertRaises(tool.ValidationError):
                tool.validate_config(value)
        value['source_types'] = ['enterprise']
        self.assertEqual(tool.validate_config(value)['source_types'], ['enterprise'])

    def test_only_selected_topic_requires_topics(self):
        value = config()
        value['require_topic_match'] = True
        with self.assertRaisesRegex(tool.ValidationError, 'topics'):
            tool.validate_config(value)
        value['topics'] = ['绿色循环']
        self.assertTrue(tool.validate_config(value)['require_topic_match'])
        value['require_topic_match'] = 1
        with self.assertRaises(tool.ValidationError):
            tool.validate_config(value)


class JsonTests(unittest.TestCase):
    def check_bad(self, content):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'data.json'
            path.write_bytes(content)
            with self.assertRaises(tool.ValidationError):
                tool.load_json(path)

    def test_duplicate_keys(self):
        self.check_bad(b'{"a": {"b": 1, "b": 2}}')

    def test_non_finite(self):
        for value in (b'NaN', b'Infinity', b'-Infinity', b'1e9999'):
            with self.subTest(value=value):
                self.check_bad(value)

    def test_size_cap(self):
        self.check_bad(b' ' * (tool.MAX_BYTES + 1))

    def test_encoding_and_syntax(self):
        for content in (b'\xff', b'{', b'{} garbage'):
            with self.subTest(content=content):
                self.check_bad(content)

    def test_valid_json(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'data.json'
            path.write_text('{"value": 1.5}', encoding='utf-8')
            self.assertEqual(tool.load_json(path), {'value': 1.5})


class WindowTests(unittest.TestCase):
    def test_daily_previous_day(self):
        value = tool.compute_window('daily', '2024-03-01T09:00:00+08:00')
        self.assertEqual(value['start'], '2024-02-29T00:00:00+08:00')
        self.assertEqual(value['cutoff'], '2024-03-01T09:00:00+08:00')

    def test_weekly_iso_cross_year(self):
        value = tool.compute_window('weekly', '2021-01-04T09:00:00+08:00')
        self.assertEqual(value['start'], '2020-12-28T00:00:00+08:00')
        self.assertEqual(value['end_exclusive'], '2021-01-04T00:00:00+08:00')
        explicit = tool.compute_window('weekly', '2021-01-04T09:00:00+08:00', '2020-W53')
        self.assertEqual(value, explicit)

    def test_monthly_leap_and_year(self):
        self.assertEqual(tool.compute_window('monthly', '2024-03-03T00:00:00Z')['start'], '2024-02-01T00:00:00+08:00')
        self.assertEqual(tool.compute_window('monthly', '2024-01-02T00:00:00Z')['start'], '2023-12-01T00:00:00+08:00')

    def test_current_period_cutoff(self):
        for kind, period in [('daily', '2024-03-15'), ('weekly', '2024-W11'), ('monthly', '2024-03')]:
            value = tool.compute_window(kind, '2024-03-15T09:00:00+08:00', period)
            self.assertEqual(value['cutoff'], '2024-03-15T09:00:00+08:00')

    def test_current_period_end_clipped_and_zero_rejected(self):
        value = tool.compute_window('daily', '2024-03-15T09:00:00+08:00', '2024-03-15')
        self.assertEqual(value['end_exclusive'], value['cutoff'])
        with self.assertRaises(tool.ValidationError):
            tool.compute_window('daily', '2024-03-15T00:00:00+08:00', '2024-03-15')

    def test_future_period(self):
        for kind, period in [('daily', '2024-03-16'), ('weekly', '2024-W12'), ('monthly', '2024-04')]:
            with self.subTest(kind=kind), self.assertRaises(tool.ValidationError):
                tool.compute_window(kind, '2024-03-15T09:00:00+08:00', period)

    def test_strict_periods(self):
        for kind, period in [('daily', '2024-2-01'), ('daily', '2023-02-29'), ('weekly', '2024-W1'), ('weekly', '2021-W53'), ('monthly', '2024-2'), ('monthly', '2024-13')]:
            with self.subTest(period=period), self.assertRaises(tool.ValidationError):
                tool.compute_window(kind, '2025-01-01T00:00:00Z', period)

    def test_no_timezone(self):
        with self.assertRaises(tool.ValidationError):
            tool.compute_window('daily', '2024-03-15T09:00:00')

    def test_invalid_timezone_offsets(self):
        for offset in ('+08:60', '+08:99', '-10:99', '+24:00'):
            with self.subTest(offset=offset), self.assertRaises(tool.ValidationError):
                tool.compute_window('daily', '2024-03-15T09:00:00' + offset)

    def test_timezone_converted(self):
        self.assertEqual(tool.compute_window('daily', '2024-03-01T17:00:00Z')['start'], '2024-03-01T00:00:00+08:00')


class RenderTests(unittest.TestCase):
    def assert_bad(self, value, path=None):
        with self.assertRaises(tool.ValidationError) as ctx:
            tool.render_report(value)
        if path:
            self.assertIn(path, str(ctx.exception))

    def test_deterministic_complete_html(self):
        data = report()
        output = tool.render_report(data)
        self.assertEqual(output, tool.render_report(copy.deepcopy(data)))
        self.assertIn('公开事实', output)
        self.assertIn('研究关注', output)
        self.assertIn('检索：2024-02-29T12:00:00+08:00', output)
        self.assertIn('href="https://example.com/article?a=1&amp;b=2"', output)
        self.assertNotIn('<script', output)

    def test_morning_retrieval_after_publication_window(self):
        data = report()
        data['period']['cutoff'] = '2024-03-01T07:00:00+08:00'
        data['items'][0]['sources'][0]['retrieved_at'] = '2024-03-01T06:00:00+08:00'
        output = tool.render_report(data)
        self.assertIn('检索：2024-03-01T06:00:00+08:00', output)
        self.assertIn('本报告基于公开信息整理', output)
        self.assertIn('苏州市公开事项', output)
        self.assertNotIn('全省公开信息', output)
        self.assertIn('仅汇总已有记录', output)

    def test_independent_requires_two_distinct_urls(self):
        data = report()
        item = data['items'][0]
        item['verification'] = 'independent_verified'
        self.assert_bad(data, '.sources')
        item['sources'].append(copy.deepcopy(item['sources'][0]))
        self.assert_bad(data, '.sources')
        item['sources'][1]['url'] = 'https://example.org/article'
        self.assertIn('独立来源已核实', tool.render_report(data))

    def test_xss_escaped(self):
        data = report()
        payload = '<script>alert("x")</script>'
        data['title'] = payload
        data['items'][0]['summary'] = payload
        data['items'][0]['sources'][0]['name'] = payload
        output = tool.render_report(data)
        self.assertNotIn('<script>', output)
        self.assertGreaterEqual(output.count('&lt;script&gt;'), 4)

    def test_unsafe_urls(self):
        urls = ['file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,hi', 'https://u:p@example.com', 'http://localhost/x', 'http://a.localhost./', 'http://127.0.0.1', 'http://10.1.2.3', 'http://172.16.0.1', 'http://192.168.1.1', 'http://169.254.169.254', 'http://0.0.0.0', 'http://[::1]', 'http://[::ffff:127.0.0.1]', 'http://2130706433', 'http://127.1', 'http://0x7f000001', 'http://0177.0.0.1', 'https://a.internal', 'https://a.local', 'https://example.com\\@localhost', 'https://example.com:99999', 'https://exa mple.com']
        for url in urls:
            data = report()
            data['items'][0]['sources'][0]['url'] = url
            with self.subTest(url=url):
                self.assert_bad(data, '.url')

    def test_credential_query_and_fragment_urls(self):
        for component in ('?token=SECRET', '?ACCESS_TOKEN=SECRET', '?api_key=SECRET', '?key=SECRET', '?authorization=SECRET', '?signature=SECRET', '?X-Amz-Signature=SECRET', '?X-Amz-Credential=SECRET', '?X-Goog-Signature=SECRET', '#access_token=SECRET', '#/route?access_token=SECRET', '?%74oken=SECRET'):
            with self.subTest(component=component), self.assertRaises(tool.ValidationError) as ctx:
                tool.safe_url('https://example.com/a' + component, '$.url')
            self.assertNotIn('SECRET', str(ctx.exception))

    def test_expected_days_matches_natural_days(self):
        data = report()
        data['kind'] = 'monthly'
        data['period']['start'] = '2024-02-01T00:00:00+08:00'
        self.assert_bad(data, '$.coverage.expected_days')
        data['coverage'].update(expected_days=29, available_days=29)
        self.assertIn('29/29 天', tool.render_report(data))
        data['period']['end_exclusive'] = '2024-03-01T01:00:00+08:00'
        data['period']['cutoff'] = '2024-03-01T07:00:00+08:00'
        self.assert_bad(data, '$.period.end_exclusive')

    def test_item_date_requires_matching_source(self):
        data = report()
        data['items'][0]['sources'][0]['published_at'] = '2024-02-28T10:00:00+08:00'
        self.assert_bad(data, '$.items[0].published_at')
        source = copy.deepcopy(data['items'][0]['sources'][0])
        source.update(url='https://example.org/a', published_at='2024-02-29T02:00:00Z')
        data['items'][0]['sources'].append(source)
        self.assertIn('公开事实', tool.render_report(data))

    def test_public_urls(self):
        for url in ['https://example.com', 'http://8.8.8.8/info', 'https://[2606:4700:4700::1111]/']:
            self.assertEqual(tool.safe_url(url, '$.url'), url)

    def test_missing_source(self):
        data = report()
        data['items'][0]['sources'] = []
        self.assert_bad(data, '.sources')

    def test_missing_field(self):
        data = report()
        del data['items'][0]['summary']
        self.assert_bad(data, '$.items[0].summary')

    def test_unknown_fields_everywhere(self):
        for getter in (lambda d: d, lambda d: d['period'], lambda d: d['coverage'], lambda d: d['items'][0], lambda d: d['items'][0]['sources'][0]):
            data = report()
            getter(data)['extra'] = True
            self.assert_bad(data)

    def test_empty_formal_and_observation(self):
        data = report()
        data['items'] = []
        self.assert_bad(data, '$.items')
        data['status'] = 'observation'
        self.assertIn('暂无已核实事项', tool.render_report(data))

    def test_formal_coverage_gap(self):
        data = report()
        data['coverage']['gaps'] = ['2024-02-29']
        self.assert_bad(data, '$.coverage')
        data['status'] = 'observation'
        self.assertIn('覆盖缺口', tool.render_report(data))

    def test_formal_available_short(self):
        data = report()
        data['coverage']['available_days'] = 0
        self.assert_bad(data, '$.coverage')

    def test_bool_counts(self):
        for field in ('expected_days', 'available_days'):
            data = report()
            data['coverage'][field] = True
            self.assert_bad(data, '$.coverage.' + field)

    def test_unverified_rejected_in_all_statuses(self):
        for status in ('formal', 'observation'):
            data = report()
            data['status'] = status
            data['items'][0]['verification'] = 'unverified'
            self.assert_bad(data, '.verification')

    def test_duplicate_ids_events(self):
        for field in ('id', 'event_key'):
            data = report()
            second = copy.deepcopy(data['items'][0])
            second['id'] = 'item-2'
            second['event_key'] = 'event-2'
            second[field] = data['items'][0][field]
            data['items'].append(second)
            self.assert_bad(data, '.' + field)

    def test_item_outside_period_or_future(self):
        for published in ('2024-02-28T23:59:59+08:00', '2024-03-01T00:00:00+08:00', '2024-02-29T23:00:00+08:00'):
            data = report()
            data['period']['end_exclusive'] = '2024-02-29T22:00:00+08:00'
            data['period']['cutoff'] = '2024-02-29T22:00:00+08:00'
            data['status'] = 'observation'
            data['coverage']['gaps'] = ['部分周期']
            data['items'][0]['published_at'] = published
            self.assert_bad(data, '.published_at')

    def test_source_future_and_retrieval_order(self):
        for published, retrieved in [('2024-03-02T00:00:00Z', '2024-03-02T01:00:00Z'), ('2024-02-29T10:00:00+08:00', '2024-03-02T00:00:00Z'), ('2024-02-29T10:00:00+08:00', '2024-02-29T09:00:00+08:00')]:
            data = report()
            data['items'][0]['sources'][0].update(published_at=published, retrieved_at=retrieved)
            self.assert_bad(data, '.sources[0]')

    def test_naive_timestamp(self):
        data = report()
        data['items'][0]['sources'][0]['retrieved_at'] = '2024-02-29T12:00:00'
        self.assert_bad(data, '.retrieved_at')

    def test_invalid_period_order(self):
        data = report()
        data['period']['cutoff'] = '2024-02-29T00:00:00+08:00'
        self.assert_bad(data, '$.period')

    def test_event_date_future(self):
        data = report()
        data['items'][0]['event_date'] = '2024-03-02'
        self.assert_bad(data, '.event_date')

    def test_monthly_sections(self):
        data = report()
        data['kind'] = 'monthly'
        data['period']['start'] = '2024-02-01T00:00:00+08:00'
        data['coverage'].update(expected_days=29, available_days=29)
        data['sections'] = [{'heading': '专题', 'body': '判断', 'evidence_ids': ['item-1']}]
        self.assertIn('href="#item-1"', tool.render_report(data))
        data['sections'][0]['evidence_ids'] = []
        self.assert_bad(data, '.evidence_ids')
        data['sections'][0]['evidence_ids'] = ['absent']
        self.assert_bad(data, '.evidence_ids')

    def test_daily_weekly_sections(self):
        for kind in ('daily', 'weekly'):
            data = report()
            data['kind'] = kind
            if kind == 'weekly':
                data['period'].update(start='2024-02-26T00:00:00+08:00', end_exclusive='2024-03-04T00:00:00+08:00', cutoff='2024-03-04T07:00:00+08:00')
                data['coverage'].update(expected_days=7, available_days=7)
            data['sections'] = [{'heading': '周期信号', 'body': '判断', 'evidence_ids': ['item-1']}]
            with self.subTest(kind=kind):
                self.assertIn('href="#item-1"', tool.render_report(data))


class NewPresentationTests(unittest.TestCase):
    def test_summary_is_provided_content_with_traceable_ids(self):
        data = report()
        data['summary'] = {'text': '企业披露项目处于规划公示阶段，尚未披露开工进展。', 'evidence_ids': ['item-1']}
        rendered = tool.render_report(data)
        self.assertIn(data['summary']['text'], rendered)
        self.assertLess(rendered.index('class="dashboard"'), rendered.index('id="glance"'))
        self.assertLess(rendered.index('id="glance"'), rendered.index('class="source-section"'))
        self.assertNotIn('本期核实1条', rendered)
        self.assertNotIn('data:image/png', rendered)
        self.assertNotIn('导出分享', rendered)

    def test_missing_summary_is_not_invented(self):
        data = report()
        data['sections'] = [{'heading': '方法', 'body': '这不是本期内容摘要。', 'evidence_ids': ['item-1']}]
        rendered = tool.render_report(data)
        self.assertIn('内容摘要尚未编制', rendered)
        self.assertNotIn('本期核实', rendered)

    def test_summary_references_must_be_present_unique_and_nonempty(self):
        for ids in ([], ['unknown'], ['item-1', 'item-1']):
            data = report()
            data['summary'] = {'text': '项目安排', 'evidence_ids': ids}
            with self.subTest(ids=ids), self.assertRaisesRegex(tool.ValidationError, 'summary.evidence_ids'):
                tool.validate_report(data)

    def test_no_summary_without_facts(self):
        data = report()
        data.update(status='observation', items=[])
        data['summary'] = {'text': '不能在无数据时写事实。', 'evidence_ids': []}
        with self.assertRaisesRegex(tool.ValidationError, 'summary.evidence_ids'):
            tool.validate_report(data)

    def test_classification_is_explicit_and_safe(self):
        data = report()
        item = data['items'][0]
        item.update(theme='绿色循环', stage='环评拟批准', publisher_type='enterprise')
        rendered = tool.render_report(data)
        self.assertIn('企业资讯', rendered)
        self.assertNotIn('非承载网站', rendered)
        self.assertNotIn('精确分配', rendered)
        self.assertIn('绿色循环', rendered)
        item['publisher_type'] = 'private'
        with self.assertRaisesRegex(tool.ValidationError, 'publisher_type'):
            tool.validate_report(data)

    def test_new_content_fields_are_escaped(self):
        data = report()
        payload = '<img src=x onerror=alert(1)>'
        data['summary'] = {'text': payload, 'evidence_ids': ['item-1']}
        data['items'][0].update(theme=payload, stage=payload, publisher_type='gov')
        rendered = tool.render_report(data)
        self.assertNotIn('<img ', rendered)
        self.assertIn('&lt;img ', rendered)
        self.assertNotIn('<script', rendered)

    def test_partial_period_requires_gap_and_visible_label(self):
        data = report()
        data.update(kind='monthly', status='observation')
        data['period'].update(start='2024-02-01T00:00:00+08:00', end_exclusive='2024-02-29T14:00:00+08:00', cutoff='2024-02-29T14:00:00+08:00')
        data['coverage'].update(expected_days=29, available_days=29)
        with self.assertRaisesRegex(tool.ValidationError, 'coverage.gaps'):
            tool.validate_report(data)
        data['coverage']['gaps'] = ['截至当日14时，非完整月。']
        rendered = tool.render_report(data)
        self.assertIn('部分月报', rendered)
        self.assertIn('截至当日14时，非完整月。', rendered[:rendered.index('<section class="dashboard"')])


class PublicationTests(unittest.TestCase):
    def test_theme_map_includes_unclassified_items(self):
        data = report()
        data['items'][0].update(theme='绿色循环', publisher_type='gov')
        second = copy.deepcopy(data['items'][0])
        second.update(id='item-2', event_key='event-2')
        second.pop('theme')
        data['items'].append(second)
        rendered = tool.render_report(data)
        self.assertIn('未分类', rendered)
        self.assertIn('未分类1条', rendered)
        block = rendered.split('class="theme-map"', 1)[1].split('</svg>', 1)[0]
        rects = re.findall(r'<rect[^>]*width="([\d.]+)" height="([\d.]+)"', block)
        self.assertEqual(len(rects), 2)
        areas = [float(w) * float(h) for w, h in rects]
        self.assertAlmostEqual(sum(areas), 64000, places=3)
        self.assertAlmostEqual(areas[0], areas[1], places=3)

    def test_all_missing_themes_are_not_hidden(self):
        rendered = tool.render_report(report())
        self.assertIn('未分类1条', rendered)
        self.assertIn('class="theme-map"', rendered)

    def test_reader_text_and_collection_details_are_both_preserved(self):
        data = report()
        data['items'][0]['summary'] = '原始采集内容，日期00:00为编码占位。'
        data['items'][0]['reader_summary'] = '项目处于环评拟批准公示。'
        rendered = tool.render_report(data)
        main_text = rendered.split('<section class="appendix">', 1)[0]
        self.assertIn('项目处于环评拟批准公示。', main_text)
        self.assertNotIn('编码占位', main_text)
        self.assertIn(data['items'][0]['summary'], rendered)

    def test_reader_analysis_keeps_evidence_without_visible_implementation_notes(self):
        data = report()
        data['items'][0]['analysis'] = '正式批复尚未公开。原文与栏目仅计一个证据根。'
        data['items'][0]['reader_analysis'] = '后续关注正式批复。'
        rendered = tool.render_report(data)
        main_text = rendered.split('<section class="appendix">', 1)[0]
        self.assertIn('后续关注正式批复。', main_text)
        self.assertNotIn('证据根', main_text)
        self.assertIn(data['items'][0]['analysis'], rendered)
        data['items'][0]['reader_analysis'] = ''
        main_text = tool.render_report(data).split('<section class="appendix">', 1)[0]
        self.assertNotIn('class="analysis"', main_text)

    def test_report_omits_implementation_notes(self):
        rendered = tool.render_report(report())
        for phrase in ('非承载网站', '矩形面积按主题事项数', '已标注', '本期样本，非全省总量'):
            self.assertNotIn(phrase, rendered)
        self.assertNotIn('class="chart-note"', rendered)


class ExportBoundaryTests(unittest.TestCase):
    def exporter(self):
        import sys
        script = SCRIPT.with_name('export_png.py')
        spec = importlib.util.spec_from_file_location('png_export_boundary', script)
        exporter = importlib.util.module_from_spec(spec)
        sys.modules['briefing_tool'] = tool
        spec.loader.exec_module(exporter)
        return exporter

    def test_existing_output_is_preserved(self):
        exporter = self.exporter()
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'share.png'
            target.write_bytes(b'existing output')
            with self.assertRaisesRegex(tool.ValidationError, '禁止覆盖'):
                exporter.export_png('not-needed.json', target)
            self.assertEqual(target.read_bytes(), b'existing output')

    def test_empty_or_unsummarized_data_cannot_export(self):
        exporter = self.exporter()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'data.json'
            target = Path(root) / 'share.png'
            data = report()
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(tool.ValidationError, 'summary'):
                exporter.export_png(path, target)
            data.update(status='observation', items=[])
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(tool.ValidationError, 'items'):
                exporter.export_png(path, target)
            self.assertFalse(target.exists())

    def test_export_parameters_are_bounded(self):
        exporter = self.exporter()
        for kwargs in ({'width': 359}, {'scale': 4}, {'scale': True}, {'browser_channel': 'remote'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(tool.ValidationError):
                exporter.export_png('not-needed.json', 'share.png', **kwargs)


class PeriodShapeTests(unittest.TestCase):
    def test_daily_cannot_span_month(self):
        data = report()
        data['period']['start'] = '2024-02-01T00:00:00+08:00'
        with self.assertRaisesRegex(tool.ValidationError, 'end_exclusive'):
            tool.validate_report(data)

    def test_weekly_must_start_monday(self):
        data = report()
        data['kind'] = 'weekly'
        with self.assertRaisesRegex(tool.ValidationError, '周一'):
            tool.validate_report(data)

    def test_monthly_must_start_first(self):
        data = report()
        data['kind'] = 'monthly'
        with self.assertRaisesRegex(tool.ValidationError, '1日'):
            tool.validate_report(data)

    def test_partial_cannot_claim_formal(self):
        data = report()
        data['period'].update(end_exclusive='2024-02-29T14:00:00+08:00', cutoff='2024-02-29T14:00:00+08:00')
        with self.assertRaisesRegex(tool.ValidationError, '部分周期'):
            tool.validate_report(data)
        data['status'] = 'observation'
        data['coverage']['gaps'] = ['部分周期，截至14时']
        self.assertIn('观察稿', tool.render_report(data))

    def test_start_must_be_midnight(self):
        data = report()
        data['period']['start'] = '2024-02-29T01:00:00+08:00'
        with self.assertRaisesRegex(tool.ValidationError, '00:00'):
            tool.validate_report(data)


class CliTests(unittest.TestCase):
    def test_exit_two_and_redacted_error(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'data.json'
            data = config()
            data['audience'] = 'private-sensitive-text'
            path.write_text(json.dumps(data), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(tool.main(['validate-config', str(path)]), 2)
            self.assertIn('$.audience', output.getvalue())
            self.assertNotIn('private-sensitive-text', output.getvalue())

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            source, target = Path(root) / 'data.json', Path(root) / 'report.html'
            source.write_text(json.dumps(report()), encoding='utf-8')
            args = ['render', '--data', str(source), '--out', str(target)]
            self.assertEqual(tool.main(args), 0)
            first = target.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(tool.main(args), 2)
            self.assertEqual(target.read_bytes(), first)

    def test_normalized_config_stdout(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'config.json'
            source.write_text(json.dumps(config()), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(tool.main(['validate-config', str(source)]), 0)
            self.assertEqual(json.loads(output.getvalue())['history_mode'], 'aggregate_only')


if __name__ == '__main__':
    unittest.main()
