#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
舆情数据分析报告流水线（移植自「数据分析报告 skill」）：
    parse   —— 读 Brandwatch mentions 导出的 xlsx，抽字段、过滤噪声 → 干净记录
    analyze —— 纯统计，产出子数据集（供 LLM 写结论 + 渲染图表）
    render  —— 子数据集 + 结论注入 ECharts 模板 → HTML 报告

设计原则（与 skill 一致）：数字全由代码算，情感/结论由 LLM 判断，代码不做算术。
"""

import io
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from openpyxl import load_workbook

# 133 列 → 关键字段（表头名 → 规范名）。未列出的平台长尾字段一律丢弃。
FIELD_MAP = {
    '情感属性': 'sentiment_cn',
    '标签列': 'tag',
    '序号': 'seq',
    '品牌类别': 'brand',
    'Date': 'date',
    '北京时间': 'beijing_time',
    'Title': 'title',
    'Snippet': 'snippet',
    'Url': 'url',
    'Domain': 'domain',
    'Sentiment': 'sentiment_en',
    'Emotion': 'emotion',
    'Page Type': 'page_type',
    'Language': 'language',
    'Country': 'country',
    'Continent': 'continent',
    'Region': 'region',
    'City': 'city',
    'Author': 'author',
    'Full Name': 'full_name',
    'Gender': 'gender',
    'Hashtags': 'hashtags',
    'Impact': 'impact',
    'Impressions': 'impressions',
    'Circulation': 'circulation',
    'Likes': 'likes',
    'Comments': 'comments',
    'Shares': 'shares',
    'Twitter Followers': 'twitter_followers',
    'Estimated Reach': 'estimated_reach',
    'Engagement Score': 'engagement_score',
    'Potential Audience': 'potential_audience',
}

NOISE_TAG = '无关'
_EXCEL_EPOCH = datetime(1899, 12, 30)
SENTI_EN = {'positive': '正面', 'negative': '负面', 'neutral': '中性'}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _cell(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _norm_time(v):
    """把时间字段统一成 'YYYY-MM-DD HH:MM' 文本。

    不同批次导出里，Date/北京时间 可能是文本、datetime 或 Excel 序列号，
    统一归一后 analyze 才能按小时正确分桶。
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d %H:%M')
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    try:
        n = float(v)
        return (_EXCEL_EPOCH + timedelta(days=n)).strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return str(v)


def num(v):
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def sentiment_of(r):
    cn = r.get('sentiment_cn')
    if cn in ('正面', '负面'):  # 人工明确判断，最优先
        return cn
    en = r.get('sentiment_en')
    if en in SENTI_EN:          # 中性/空 → 回退英文机器情感
        return SENTI_EN[en]
    return cn or '未知'


def top(items, n):
    """list[(label, count)] → 前 n + 归并'其他'"""
    items = sorted(items, key=lambda x: -x[1])
    out = [{'name': k, 'count': c} for k, c in items[:n]]
    tail = items[n:]
    if tail:
        out.append({'name': '其他', 'count': sum(c for _, c in tail)})
    return out


# ---------------------------------------------------------------------------
# ① parse
# ---------------------------------------------------------------------------
def parse(data: bytes, source_name: str = 'imported.xlsx'):
    """读取 xlsx 字节流 → (干净记录列表, 数据画像)。"""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    sheet_name = ws.title
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else None for h in next(rows)]

    col = {}
    for i, h in enumerate(header):
        if h is not None and h not in col:
            col[h] = i

    # 中文标题列：Title 之后紧跟的、非 Snippet 的那一列（列名在 中文/标题/Title 间漂移）
    title_cn_idx = None
    if 'Title' in col:
        ti = col['Title']
        if ti + 1 < len(header) and header[ti + 1] not in (None, 'Snippet'):
            title_cn_idx = ti + 1

    records, total, dropped_noise, dropped_unreviewed = [], 0, 0, 0
    for r in rows:
        total += 1
        rec = {key: _cell(r[col[name]]) for name, key in FIELD_MAP.items() if name in col}
        rec['title_cn'] = _cell(r[title_cn_idx]) if title_cn_idx is not None else None
        rec['date'] = _norm_time(rec.get('date'))
        rec['beijing_time'] = _norm_time(rec.get('beijing_time'))
        tag = rec.get('tag')
        if tag == NOISE_TAG:
            dropped_noise += 1
            continue
        if tag in (None, ''):  # 未审行：清洗字段全空，无法参与话题/情感/品牌分析
            dropped_unreviewed += 1
            continue
        records.append(rec)
    wb.close()

    profile = {
        'source_file': source_name,
        'sheet': sheet_name,
        'total_raw_rows': total,
        'kept_rows': len(records),
        'dropped_noise': dropped_noise,
        'dropped_unreviewed': dropped_unreviewed,
        'brands': sorted({r['brand'] for r in records if r.get('brand')}),
        'platforms': sorted({r['domain'] for r in records if r.get('domain')}),
        'languages': sorted({r['language'] for r in records if r.get('language')}),
        'sentiments_cn': sorted({r['sentiment_cn'] for r in records if r.get('sentiment_cn')}),
    }
    return records, profile


# ---------------------------------------------------------------------------
# ② analyze
# ---------------------------------------------------------------------------
def analyze(rows):
    def cnt(key):
        c = Counter()
        for r in rows:
            v = r.get(key)
            if v not in (None, ''):
                c[str(v)] += 1
        return c

    sentiment_c = Counter(sentiment_of(r) for r in rows)
    brand_c = cnt('brand')
    topic_c = cnt('tag')
    platform_c = cnt('domain')
    country_c = cnt('country')
    continent_c = cnt('continent')
    language_c = cnt('language')

    time_c = Counter()
    for r in rows:
        bt = r.get('beijing_time') or r.get('date')
        if bt:
            time_c[str(bt)[:13] + ':00'] += 1

    def impact_of(r):
        return num(r.get('impact')) or num(r.get('impressions'))

    ranked = sorted(rows, key=lambda r: -impact_of(r))
    top_mentions = [{
        'title': (r.get('title_cn') or r.get('title') or '')[:120],
        'tag': r.get('tag'), 'brand': r.get('brand'), 'sentiment': sentiment_of(r),
        'domain': r.get('domain'), 'country': r.get('country'),
        'author': r.get('author'), 'impact': num(r.get('impact')),
        'reach': num(r.get('estimated_reach')), 'url': r.get('url'),
    } for r in ranked[:10]]

    # 每个话题抽 3 条代表标题，供 LLM 判定情感（LLM 判，不做算术）
    topic_samples = defaultdict(list)
    for r in rows:
        t = r.get('tag')
        if t and len(topic_samples[t]) < 3:
            txt = (r.get('title_cn') or r.get('title') or '').strip()
            if txt:
                topic_samples[t].append(txt[:100])
    topics_detail = [{'name': name, 'count': count, 'samples': topic_samples.get(name, [])}
                     for name, count in topic_c.most_common()]

    return {
        'kpi': {
            'total': len(rows),
            'positive': sentiment_c.get('正面', 0),
            'neutral': sentiment_c.get('中性', 0),
            'negative': sentiment_c.get('负面', 0),
            'total_impact': sum(num(r.get('impact')) for r in rows),
            'total_reach': sum(num(r.get('estimated_reach')) for r in rows),
            'total_impressions': sum(num(r.get('impressions')) for r in rows),
            'total_audience': sum(num(r.get('potential_audience')) for r in rows),
            'total_engagement': sum(num(r.get('engagement_score')) for r in rows),
        },
        'sentiment': dict(sentiment_c),
        'brand': top(list(brand_c.items()), 6),
        'topic': top(list(topic_c.items()), 8),
        'platform': top(list(platform_c.items()), 6),
        'country': top(list(country_c.items()), 10),
        'continent': dict(continent_c),
        'language': dict(language_c),
        'time_series': [{'hour': k, 'count': v} for k, v in sorted(time_c.items())],
        'top_mentions': top_mentions,
        'topics_detail': topics_detail,
    }


# ---------------------------------------------------------------------------
# ③ 前端展示投影（把干净记录投成列表需要的最小字段）
# ---------------------------------------------------------------------------
def to_display(record):
    return {
        'index': record.get('seq'),
        'brand': record.get('brand'),
        'tag': record.get('tag'),
        'sentiment_manual': record.get('sentiment_cn'),
        'sentiment': record.get('sentiment_en'),
        'emotion': record.get('emotion'),
        'title': record.get('title'),
        'snippet': record.get('snippet'),
        'url': record.get('url'),
        'domain': record.get('domain'),
        'platform': record.get('page_type'),
        'language': record.get('language'),
        'country': record.get('country'),
        'author': record.get('author'),
        'time': record.get('beijing_time'),
    }


# ---------------------------------------------------------------------------
# ④ render
# ---------------------------------------------------------------------------
def render(subdatasets, conclusions, template_text):
    """子数据集 + 结论 → HTML 报告字符串。"""
    sub = subdatasets
    concl = conclusions or {}
    sbt = concl.get('sentiment_by_topic')  # {话题: 正面/中性/负面}，由 LLM 判定

    if sbt:
        # LLM 判定情感 → 覆盖统计与逐条情感；代码只做汇总算术
        senti = Counter()
        for t in sub.get('topics_detail', []):
            senti[sbt.get(t['name'], '中性')] += t['count']
        sub['sentiment'] = dict(senti)
        k = sub.setdefault('kpi', {})
        k['positive'] = senti.get('正面', 0)
        k['neutral'] = senti.get('中性', 0)
        k['negative'] = senti.get('负面', 0)
        for m in sub.get('top_mentions', []):
            m['sentiment'] = sbt.get(m.get('tag'), '中性')

    # 风险提及 = 热门里情感为负面的（无论情感来自 LLM 还是列）
    sub['risk_mentions'] = [m for m in sub.get('top_mentions', []) if m.get('sentiment') == '负面']

    report = {'subdatasets': sub, 'conclusions': concl}
    payload = json.dumps(report, ensure_ascii=False).replace('<', '\\u003c')
    return template_text.replace('__REPORT_DATA__', payload)
