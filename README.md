# 舆情全链路智能处置工作台

一个「全真接入」的舆情处置工具，覆盖 **采集 → 核查 → 评论 → 投诉 → 报告** 全链路，每一步都由真实大模型（DeepSeek）驱动。

## 功能模块

| 模块 | 说明 |
|---|---|
| ① 舆情采集 | 聚合真实 RSS 新闻（36氪 / 少数派 / 爱范儿），情感标注 |
| ② AI 核查 | 真实性研判（真/假/存疑）+ 证据链 + 风险等级 + 处置建议 |
| ③ AI 事实评论 | 生成符合风格的回应口径 |
| ④ AI 投诉处置 | 分类 / 优先级 / 转办部门 / 回复话术 |
| ⑤ 处置报告 | 汇总留痕 + 一键导出 .md |

## 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 Key（二选一）
#    方式 A：环境变量
#      Linux/macOS: export DEEPSEEK_API_KEY=sk-xxxx
#      Windows:     set DEEPSEEK_API_KEY=sk-xxxx
#    方式 B：在项目根目录新建 key.txt，写入 sk-xxxx（已 gitignore）

# 3. 启动
uvicorn main:app --reload
# 或
python main.py
```

打开 http://127.0.0.1:8000 即可使用。

## 部署（Render 免费版）

1. 把本目录推送到 GitHub（`key.txt` 已 gitignore，别提交真实 Key）
2. Render → New → Web Service → 连该仓库
3. Render 自动读取 `render.yaml`（Build: `pip install -r requirements.txt`，Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`）
4. 在 Environment 里加 `DEEPSEEK_API_KEY = sk-xxxx`
5. Deploy → 得到公开 URL

> 免费版冷启动 30–60 秒、15 分钟无访问自动休眠，属正常现象。

## 说明

- Key 只放两处：Render 环境变量（生产）、本地 `key.txt`（开发），绝不写进代码
- 处置留痕存浏览器 localStorage（`handling_log`），换浏览器会丢，可用「导出 .md」备份
- 无 Key 时页面会明确引导配置，不降级到假 AI、不显示写死结果

详见 [docs/技术方案.md](docs/技术方案.md) 与《产品设计文档.md》。
