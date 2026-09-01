"""舆情全链路智能处置工作台 —— FastAPI 后端。

托管前端静态页面，提供 DeepSeek 统一代理接口与 RSS 聚合接口。
DeepSeek Key 只从环境变量 DEEPSEEK_API_KEY 或本地 key.txt（已 gitignore）读取，绝不写死在代码里。
"""

import json
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# 弱采集：只接真实 RSS 新闻源
RSS_FEEDS = {
    "36氪": "https://36kr.com/feed",
    "少数派": "https://sspai.com/feed",
    "爱范儿": "https://www.ifanr.com/feed",
}

app = FastAPI(title="舆情全链路智能处置工作台")


# ---------------------------------------------------------------------------
# Key 读取
# ---------------------------------------------------------------------------
def load_api_key() -> str | None:
    """读取 DeepSeek Key：环境变量优先，其次本地 key.txt。"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key and key.strip():
        return key.strip()

    key_file = BASE_DIR / "key.txt"
    if key_file.exists():
        content = key_file.read_text(encoding="utf-8").strip()
        if content:
            return content
    return None


# ---------------------------------------------------------------------------
# DeepSeek 调用
# ---------------------------------------------------------------------------
def call_deepseek(system: str, user: str) -> str:
    """调用 DeepSeek chat 接口，返回 assistant 文本内容。"""
    key = load_api_key()
    if not key:
        raise HTTPException(status_code=400, detail="DeepSeek Key 未配置")

    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=exc.code, detail=f"DeepSeek 调用失败：{detail}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"DeepSeek 调用异常：{exc}")

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="DeepSeek 返回结构异常")


def extract_json(text: str):
    """从模型输出中稳健地提取 JSON（去掉代码块、截取首尾括号）。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    text = text.strip()

    for start, end in (("[", "]"), ("{", "}")):
        i = text.find(start)
        j = text.rfind(end)
        if i != -1 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                continue

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="DeepSeek 返回内容无法解析为 JSON")


# ---------------------------------------------------------------------------
# Prompt 拼装（前端不写 prompt，只传业务字段）
# ---------------------------------------------------------------------------
def build_prompt(task: str, payload: dict) -> tuple[str, str, bool]:
    """返回 (system, user, expect_json)。"""
    if task == "verify":
        title = (payload.get("title") or "").strip()
        content = (payload.get("content") or "").strip()
        system = "你是资深舆情真实性研判专家，依据给定信息做事实核查，只输出结构化 JSON。"
        user = (
            "请核查以下舆情信息，判断其真实性。只输出一个 JSON 对象（不要 markdown 代码块、"
            "不要多余文字），字段如下：\n"
            '{"verdict": "真/假/存疑 三选一", "risk": "高/中/低 三选一", '
            '"evidence": ["证据点1", "证据点2"], "conclusion": "处置建议"}\n\n'
            f"标题：{title or '（无）'}\n内容：{content or '（无）'}"
        )
        return system, user, True

    if task == "comment":
        event = (payload.get("event") or "").strip()
        style = (payload.get("style") or "官方权威").strip()
        system = "你是官方舆情回应专员，负责撰写事实回应口径，实事求是、不传谣不信谣。"
        user = (
            f"请针对以下舆情事件撰写一段回应评论。风格：{style}。"
            "只输出评论正文，不要任何前缀、标题或解释。\n\n"
            f"事件：{event or '（无）'}"
        )
        return system, user, False

    if task == "complaint":
        text = (payload.get("text") or "").strip()
        system = "你是政务投诉处置助手，负责对投诉分类、定级、转办并给出回复话术。"
        user = (
            "请对以下投诉文本进行处理。只输出一个 JSON 对象（不要 markdown 代码块、"
            "不要多余文字），字段如下：\n"
            '{"type": "投诉分类", "priority": "高/中/低 三选一", '
            '"dept": "建议转办部门", "reply": "回复话术"}\n\n'
            f"投诉内容：{text or '（无）'}"
        )
        return system, user, True

    if task == "sentiment":
        titles = payload.get("titles") or []
        system = "你是舆情情感分析助手，判断新闻标题的情感倾向。"
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
        user = (
            "请判断以下新闻标题的情感倾向，每个标题输出「负面」「中性」「正面」之一。"
            "只输出一个 JSON 数组（不要 markdown 代码块、不要多余文字），元素顺序与输入一致，"
            '元素值为 "负面"/"中性"/"正面"。\n\n'
            f"标题列表：\n{numbered}"
        )
        return system, user, True

    raise HTTPException(status_code=400, detail=f"未知任务类型：{task}")


# ---------------------------------------------------------------------------
# RSS 聚合
# ---------------------------------------------------------------------------
def _elem_text(parent: ET.Element, tag: str) -> str:
    el = parent.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def fetch_rss() -> list[dict]:
    """聚合各 RSS 源，返回统一的新闻条目列表；单个源失败不影响整体。"""
    items: list[dict] = []
    for source, url in RSS_FEEDS.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                root = ET.fromstring(resp.read())
            for node in root.iter("item"):
                title = _elem_text(node, "title")
                if not title:
                    continue
                items.append(
                    {
                        "title": title,
                        "source": source,
                        "time": _elem_text(node, "pubDate"),
                        "link": _elem_text(node, "link"),
                        "desc": _elem_text(node, "description"),
                    }
                )
        except Exception:  # noqa: BLE001 —— 单源失败静默跳过
            continue
    return items


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status():
    return {"deepseek": bool(load_api_key())}


@app.get("/api/rss")
def rss():
    return {"ok": True, "items": fetch_rss()}


@app.post("/api/deepseek")
def deepseek(req: dict):
    task = req.get("task")
    payload = req.get("payload") or {}
    system, user, expect_json = build_prompt(task, payload)
    raw = call_deepseek(system, user)
    if expect_json:
        return {"ok": True, "result": extract_json(raw)}
    return {"ok": True, "result": raw}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
