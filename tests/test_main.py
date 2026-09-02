"""main.py 的单元与接口测试。"""

import io
import json

import openpyxl
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
import reporting


# ---------------------------------------------------------------------------
# Prompt 拼装
# ---------------------------------------------------------------------------
def test_build_prompt_verify():
    system, user, expect_json = main.build_prompt("verify", {"title": "某公司暴雷", "content": "详情"})
    assert expect_json is True
    assert "某公司暴雷" in user and "详情" in user


def test_build_prompt_comment():
    _, user, expect_json = main.build_prompt("comment", {"event": "事件", "style": "亲民温暖"})
    assert expect_json is False
    assert "亲民温暖" in user and "事件" in user


def test_build_prompt_complaint():
    _, user, expect_json = main.build_prompt("complaint", {"text": "噪音扰民"})
    assert expect_json is True
    assert "噪音扰民" in user


def test_build_prompt_sentiment():
    _, user, expect_json = main.build_prompt("sentiment", {"titles": ["标题A", "标题B"]})
    assert expect_json is True
    assert "标题A" in user and "标题B" in user


def test_build_prompt_unknown():
    with pytest.raises(HTTPException):
        main.build_prompt("nope", {})


# ---------------------------------------------------------------------------
# JSON 提取
# ---------------------------------------------------------------------------
def test_extract_json_plain_object():
    assert main.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_codefence_object():
    assert main.extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_codefence_array():
    assert main.extract_json('```json\n["负面", "正面"]\n```') == ["负面", "正面"]


def test_extract_json_embedded():
    assert main.extract_json('结果如下：{"verdict": "真"} 完成') == {"verdict": "真"}


def test_extract_json_bad():
    with pytest.raises(HTTPException):
        main.extract_json("这里没有 JSON")


# ---------------------------------------------------------------------------
# Key 读取
# ---------------------------------------------------------------------------
def test_load_api_key_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    assert main.load_api_key() == "sk-env"


def test_load_api_key_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / "key.txt").write_text("sk-file", encoding="utf-8")
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    assert main.load_api_key() == "sk-file"


def test_load_api_key_env_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    (tmp_path / "key.txt").write_text("sk-file", encoding="utf-8")
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    assert main.load_api_key() == "sk-env"


def test_load_api_key_none(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    assert main.load_api_key() is None


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
def test_index_endpoint():
    client = TestClient(main.app)
    r = client.get("/")
    assert r.status_code == 200
    assert "舆情全链路智能处置工作台" in r.text


def test_static_no_cache():
    client = TestClient(main.app)
    r = client.get("/")
    assert r.headers.get("cache-control") == "no-store"


def test_status_endpoint():
    client = TestClient(main.app)
    r = client.get("/api/status")
    assert r.status_code == 200
    assert "deepseek" in r.json()


def test_deepseek_no_key_returns_400(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    client = TestClient(main.app)
    r = client.post("/api/deepseek", json={"task": "comment", "payload": {"event": "x"}})
    assert r.status_code == 400


def test_deepseek_unknown_task(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    client = TestClient(main.app)
    r = client.post("/api/deepseek", json={"task": "bogus", "payload": {}})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Key 保存 / 脱敏 / 来源
# ---------------------------------------------------------------------------
def test_save_api_key_writes_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    main.save_api_key("  sk-new  ")
    assert (tmp_path / "key.txt").read_text(encoding="utf-8") == "sk-new"
    assert main.load_api_key() == "sk-new"


def test_save_api_key_empty_clears_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    (tmp_path / "key.txt").write_text("sk-old", encoding="utf-8")
    main.save_api_key("")
    assert not (tmp_path / "key.txt").exists()
    assert main.load_api_key() is None


def test_key_source_env_vs_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    assert main.key_source() is None
    (tmp_path / "key.txt").write_text("sk-file", encoding="utf-8")
    assert main.key_source() == "file"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    assert main.key_source() == "env"


def test_mask_key():
    assert main.mask_key(None) == ""
    assert main.mask_key("short") == "sk-****"
    assert main.mask_key("sk-abcdefghijklmnop") == "sk-abc****mnop"


def test_set_key_endpoint(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    client = TestClient(main.app)
    r = client.post("/api/key", json={"key": "sk-new"})
    assert r.status_code == 200
    assert r.json()["deepseek"] is True
    assert (tmp_path / "key.txt").read_text(encoding="utf-8") == "sk-new"


def test_set_key_endpoint_clear(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    (tmp_path / "key.txt").write_text("sk-old", encoding="utf-8")
    client = TestClient(main.app)
    r = client.post("/api/key", json={"key": ""})
    assert r.status_code == 200
    assert r.json()["deepseek"] is False
    assert not (tmp_path / "key.txt").exists()


def test_status_includes_source_and_masked(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    (tmp_path / "key.txt").write_text("sk-abcdefghijklmnop", encoding="utf-8")
    client = TestClient(main.app)
    data = client.get("/api/status").json()
    assert data["deepseek"] is True
    assert data["source"] == "file"
    assert "****" in data["masked"]


# ---------------------------------------------------------------------------
# 舆情导入（.xlsx 解析 + 接口）
# ---------------------------------------------------------------------------
def _make_xlsx_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


IMPORT_HEADER = [
    "情感属性", "标签列", "序号", "品牌类别", "Date", "北京时间", "Title",
    "Snippet", "Url", "Domain", "Sentiment", "Emotion", "Page Type",
    "Language", "Country", "Author",
]


def test_reporting_parse_filters_noise_and_unreviewed():
    data = _make_xlsx_bytes([
        IMPORT_HEADER,
        ["正面", "红旗出海", "1", "红旗", 46139.0, 46139.5, "Hongqi enters Malaysia",
         "Chinese luxury brand enters Malaysia", "http://x", "facebook.com", "positive",
         "", "facebook_public", "en", "Malaysia", "Marketing"],
        ["", "无关", "2", "", 46139.0, 46139.5, "if we faw", "if we faw",
         "http://y", "twitter.com", "negative", "Anger", "twitter", "en", "", "kiya"],
        ["", "", "3", "解放", 46139.0, 46139.5, "unreviewed", "", "", "", "", "", "", "", "", ""],
        [None] * len(IMPORT_HEADER),  # 全空行 → 按 skill 口径计为「未审」
    ])
    records, profile = reporting.parse(data, "test.xlsx")
    assert len(records) == 1  # 无关被过滤、未审（空标签）被过滤
    assert profile["total_raw_rows"] == 4
    assert profile["kept_rows"] == 1
    assert profile["dropped_noise"] == 1
    assert profile["dropped_unreviewed"] == 2  # 空标签行 + 全空行
    rec = records[0]
    assert rec["brand"] == "红旗"
    assert rec["tag"] == "红旗出海"
    assert rec["sentiment_cn"] == "正面"
    assert rec["sentiment_en"] == "positive"
    assert rec["beijing_time"].startswith("2026-")


def test_reporting_parse_skips_empty():
    data = _make_xlsx_bytes([IMPORT_HEADER, [None] * len(IMPORT_HEADER)])
    records, _ = reporting.parse(data, "empty.xlsx")
    assert records == []


def test_reporting_to_display_projection():
    rec = {"seq": "1", "brand": "红旗", "tag": "出海", "sentiment_cn": "正面",
           "sentiment_en": "positive", "emotion": "", "title": "t", "snippet": "s",
           "url": "http://x", "domain": "twitter.com", "page_type": "twitter",
           "language": "en", "country": "Malaysia", "author": "a", "beijing_time": "2026-04-27 12:30"}
    d = reporting.to_display(rec)
    assert d["index"] == "1"
    assert d["sentiment_manual"] == "正面"
    assert d["sentiment"] == "positive"
    assert d["platform"] == "twitter"
    assert d["time"] == "2026-04-27 12:30"


def test_import_endpoint():
    data = _make_xlsx_bytes([
        IMPORT_HEADER,
        ["中性", "红旗营销", "1", "红旗", 46139.0, 46139.5, "title here",
         "snippet here", "http://x", "twitter.com", "neutral", "", "twitter", "en", "", "CC"],
    ])
    client = TestClient(main.app)
    r = client.post("/api/import", content=data, headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert len(items) == 1
    assert items[0]["title"] == "title here"
    assert items[0]["platform"] == "twitter"
    assert items[0]["sentiment_manual"] == "中性"
    assert body["profile"]["kept_rows"] == 1
    assert len(main.LAST_IMPORT) == 1  # 导入后缓存干净记录供报告使用


def test_import_endpoint_bad_file():
    client = TestClient(main.app)
    r = client.post("/api/import", content=b"not an xlsx", headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 数据分析报告（analyze / render / build_prompt / /api/report）
# ---------------------------------------------------------------------------
def _sample_records():
    return [
        {"seq": "1", "brand": "红旗", "tag": "出海", "sentiment_cn": "正面", "sentiment_en": "positive",
         "beijing_time": "2026-04-27 12:30", "date": None, "domain": "twitter.com",
         "country": "Malaysia", "author": "a", "url": "http://x", "title": "t1", "title_cn": None,
         "impact": 10, "impressions": 5, "estimated_reach": 100, "potential_audience": 50,
         "engagement_score": 2},
        {"seq": "2", "brand": "红旗", "tag": "出海", "sentiment_cn": "", "sentiment_en": "negative",
         "beijing_time": "2026-04-27 13:00", "date": None, "domain": "facebook.com",
         "country": "Malaysia", "author": "b", "url": "http://y", "title": "t2", "title_cn": None,
         "impact": 3, "impressions": 0, "estimated_reach": 20, "potential_audience": 10,
         "engagement_score": 1},
    ]


def test_reporting_analyze():
    sub = reporting.analyze(_sample_records())
    assert sub["kpi"]["total"] == 2
    assert sub["sentiment"]["正面"] == 1
    assert sub["sentiment"]["负面"] == 1
    assert sub["brand"][0]["name"] == "红旗"
    assert sub["topic"][0]["name"] == "出海"
    assert sub["topic"][0]["count"] == 2
    assert len(sub["time_series"]) == 2
    assert sub["top_mentions"][0]["title"] == "t1"  # impact 高者在前


def test_reporting_render_overrides_sentiment():
    sub = {
        "kpi": {"total": 1, "positive": 0, "neutral": 0, "negative": 0},
        "sentiment": {},
        "topics_detail": [{"name": "出海", "count": 1, "samples": ["t1"]}],
        "top_mentions": [{"title": "t1", "tag": "出海", "sentiment": "中性"}],
    }
    concl = {"title": "红旗舆情日报", "overview": "", "sentiment_by_topic": {"出海": "负面"}, "sections": {}}
    html = reporting.render(sub, concl, "<html>__REPORT_DATA__</html>")
    assert "__REPORT_DATA__" not in html
    assert "红旗舆情日报" in html
    assert "负面" in html  # LLM 判定的负面情感被写入 top_mentions 与 risk_mentions


def test_build_prompt_report():
    system, user, expect_json = main.build_prompt("report", {"subdatasets": {"kpi": {"total": 10}}})
    assert expect_json is True
    assert "sentiment_by_topic" in user
    assert "kpi" in user


def test_report_endpoint(monkeypatch):
    monkeypatch.setattr(main, "LAST_IMPORT", _sample_records())
    monkeypatch.setattr(main, "LAST_IMPORT_NAME", "test.xlsx")
    conclusions = {
        "title": "红旗舆情日报",
        "overview": "总体平稳",
        "sentiment_by_topic": {"出海": "正面"},
        "sections": {"sentiment": "", "brand": "", "topic": "", "platform": "",
                     "region": "", "time": "", "top": "", "risk": ""},
    }
    monkeypatch.setattr(main, "call_deepseek", lambda s, u: json.dumps(conclusions, ensure_ascii=False))
    client = TestClient(main.app)
    r = client.post("/api/report")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["title"] == "红旗舆情日报"
    assert body["name"] == "test.xlsx"
    assert "红旗舆情日报" in body["html"]


def test_report_endpoint_no_import(monkeypatch):
    monkeypatch.setattr(main, "LAST_IMPORT", [])
    client = TestClient(main.app)
    r = client.post("/api/report")
    assert r.status_code == 400
