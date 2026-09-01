"""main.py 的单元与接口测试。"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


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
