# 舆情全链路智能处置工作台

一个「全真接入」的舆情处置工具，覆盖 **采集 → 核查 → 评论 → 投诉 → 报告** 全链路，每一步都由真实大模型（DeepSeek）驱动。

## 一键启动（Windows）

双击 `一键启动.bat` 即可：自动创建虚拟环境（首次）→ 安装依赖 → 启动服务 → 打开浏览器。停止服务请关闭弹出的「Opinion Workbench Server」窗口。

## 功能模块

| 模块 | 说明 |
|---|---|
| ① 舆情采集 | 导入「社交平台」舆情 Excel（Brandwatch 导出）或聚合 RSS 新闻，选择研判对象 |
| ② AI 核查 | 真实性研判（真/假/存疑）+ 证据链 + 风险等级 + 处置建议 |
| ③ AI 事实评论 | 生成符合风格的回应口径 |
| ④ AI 投诉处置 | 分类 / 优先级 / 转办部门 / 回复话术 |
| ⑤ 处置报告 | 汇总留痕 + 一键导出 .md |
| ⑥ 数据分析报告 | 对导入的舆情数据做统计 + DeepSeek 写结论，生成可视化 HTML 报告 |

## 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 Key（三选一）
#    方式 A：启动后点页面右上角的 Key 徽标，直接在界面里粘贴保存（推荐）
#    方式 B：环境变量
#      Linux/macOS: export DEEPSEEK_API_KEY=sk-xxxx
#      Windows:     set DEEPSEEK_API_KEY=sk-xxxx
#    方式 C：在项目根目录新建 key.txt，写入 sk-xxxx（已 gitignore）

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

- Key 只放两处：Render 环境变量（生产）、本地 `key.txt`（开发，可在页面里直接填写保存），绝不写进代码
- 「导入舆情 Excel」：选择 Brandwatch mentions 导出的 .xlsx，自动识别「情感属性 / 标签列 / 品牌类别 / 情感 / 平台 / 国家」等字段；默认隐藏「无关」条目，点「选为研判对象」即可进入核查/评论
- 「数据分析报告」：导入 Excel 后，切到「⑥ 数据分析报告」点「生成报告」，程序自动统计情感 / 品牌 / 话题 / 平台 / 地区 / 时间趋势（数字全由代码算），再由 DeepSeek 判话题情感、写结论，渲染成可视化 HTML 报告，可「新窗口打开」查看
- 处置留痕存浏览器 localStorage（`handling_log`），换浏览器会丢，可用「导出 .md」备份
- 无 Key 时页面会明确引导配置，不降级到假 AI、不显示写死结果

详见 [docs/技术方案.md](docs/技术方案.md) 与《产品设计文档.md》。
