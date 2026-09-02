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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import reporting

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


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """本地工具：静态页面不缓存，改动后浏览器刷新即生效，无需手动清缓存。"""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


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


def key_source() -> str | None:
    """返回当前 Key 来源：'env' / 'file' / None（便于前端区分能否在界面里修改）。"""
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return "env"
    if (BASE_DIR / "key.txt").exists():
        return "file"
    return None


def save_api_key(key: str) -> None:
    """把 Key 写入本地 key.txt；传入空串则清除。环境变量 Key 优先级更高，不影响此文件。"""
    key_file = BASE_DIR / "key.txt"
    key = (key or "").strip()
    if key:
        key_file.write_text(key, encoding="utf-8")
    elif key_file.exists():
        key_file.unlink()


def mask_key(key: str | None) -> str:
    """只返回脱敏后的 Key，用于前端显示，避免完整 Key 泄露到页面。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "sk-****"
    return f"{key[:6]}****{key[-4:]}"


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

    if task == "report":
        sub = payload.get("subdatasets") or {}
        system = "你是资深舆情分析专家，基于给定统计摘要写分析结论。数字已由程序算好，你只做判断与解读，禁止自己算数或复述数字。"
        user = (
            "请阅读以下统计摘要（JSON），写出一份舆情日报的结论。只输出一个 JSON 对象"
            "（不要 markdown 代码块、不要多余文字），字段如下：\n"
            '{"title": "报告标题", "overview": "一句话总览", '
            '"sentiment_by_topic": {"话题名": "正面/中性/负面"}, '
            '"sections": {"sentiment": "", "brand": "", "topic": "", "platform": "", '
            '"region": "", "time": "", "top": "", "risk": ""}}\n\n'
            "要求：\n"
            "- title 用「品牌名 + 舆情日报」这类简洁标题；overview 一句话概括总体态势。\n"
            "- sentiment_by_topic：对 topics_detail 里每个话题，读它的代表标题 samples，"
            '判断该话题整体是「正面」「中性」「负面」，只写这三个词之一。\n'
            "- sections 每段 1–3 句，回答「数据说明了什么 / 意味着什么」，禁止复述数字本身。\n"
            "- 必须点出的风险信号：负面占比高、单一话题过载、某地区/品牌异常。\n\n"
            f"统计摘要（JSON）：\n{json.dumps(sub, ensure_ascii=False)}"
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
# 数据分析报告（移植自「数据分析报告 skill」的四步流水线）
# ---------------------------------------------------------------------------
# 最近一次导入的干净记录（reporting.parse 产出），供 /api/report 直接统计
LAST_IMPORT: list = []
LAST_IMPORT_NAME: str = ""

# ECharts 报告模板（含 __REPORT_DATA__ 占位符），启动时读入内存
REPORT_TEMPLATE = (BASE_DIR / "templates" / "report.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status():
    key = load_api_key()
    return {
        "deepseek": bool(key),
        "source": key_source(),
        "masked": mask_key(key),
    }


@app.post("/api/key")
def set_key(req: dict):
    """在界面里直接配置/清除 DeepSeek Key（写入本地 key.txt，已 gitignore）。"""
    save_api_key(req.get("key") or "")
    return {"ok": True, "deepseek": bool(load_api_key())}


@app.get("/api/rss")
def rss():
    return {"ok": True, "items": fetch_rss()}


@app.post("/api/import")
async def import_mentions(request: Request):
    """接收前端以二进制上传的 .xlsx，解析并返回归一化舆情条目列表。"""
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="未收到文件内容")
    try:
        records, profile = reporting.parse(body, "upload.xlsx")
    except Exception as exc:  # noqa: BLE001 —— 解析失败要给用户可读提示
        raise HTTPException(status_code=400, detail=f"解析 Excel 失败：{exc}")
    if not records:
        raise HTTPException(status_code=400, detail="未能从文件中解析出任何舆情条目")

    # 缓存干净记录 + 画像，供「数据分析报告」直接统计
    global LAST_IMPORT, LAST_IMPORT_NAME
    LAST_IMPORT = records
    LAST_IMPORT_NAME = profile.get("source_file") or "upload.xlsx"

    items = [reporting.to_display(r) for r in records]
    return {"ok": True, "items": items, "profile": profile}


@app.post("/api/deepseek")
def deepseek(req: dict):
    task = req.get("task")
    payload = req.get("payload") or {}
    system, user, expect_json = build_prompt(task, payload)
    raw = call_deepseek(system, user)
    if expect_json:
        return {"ok": True, "result": extract_json(raw)}
    return {"ok": True, "result": raw}


@app.post("/api/report")
def report():
    """对最近一次导入的舆情数据：统计 → LLM 写结论 → 渲染 HTML 报告。"""
    if not LAST_IMPORT:
        raise HTTPException(status_code=400, detail="尚未导入舆情数据，请先在「舆情采集」导入 Excel")

    subdatasets = reporting.analyze(LAST_IMPORT)

    # 「数字由代码算，情感/结论由 LLM 判」：把子数据集交给 DeepSeek
    system, user, _ = build_prompt("report", {"subdatasets": subdatasets})
    raw = call_deepseek(system, user)
    conclusions = extract_json(raw)
    if not isinstance(conclusions, dict):
        conclusions = {}

    html = reporting.render(subdatasets, conclusions, REPORT_TEMPLATE)
    return {
        "ok": True,
        "html": html,
        "title": conclusions.get("title") or "舆情日报",
        "name": LAST_IMPORT_NAME,
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
