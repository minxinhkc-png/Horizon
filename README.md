# Horizon - 自动化金融新闻分析系统

每日自动抓取全球财经新闻，使用 DeepSeek LLM 进行智能分析，输出美股/A股影响研判、行业分析、个股推荐，并通过 Telegram 推送日报。

## 架构

```
RSS Sources → 抓取/去重/清洗 → DeepSeek 三步分析 → 报告生成(MD/JSON) → Telegram推送
                                              ↓
                                         Token消耗记录
```

**三步分析流程**：
1. **摘要提炼** — 从原始新闻中提取5-10条核心信息
2. **市场影响** — 判断美股/A股趋势，识别利多/利空行业
3. **个股关联** — 推导可能受影响的具体个股及关联逻辑

## 项目结构

```
Horizon/
├── main.py                          # 主入口
├── .env                              # 本地环境变量
├── config/
│   ├── sources.yaml                 # 新闻源配置
│   └── models.yaml                  # LLM模型 & Prompt配置
├── src/
│   ├── fetcher.py                   # RSS抓取模块
│   ├── analyzer.py                  # DeepSeek API分析模块
│   ├── report.py                    # 报告生成模块
│   ├── telegram.py                  # Telegram推送模块
│   └── token_tracker.py             # Token消耗追踪模块
├── data/
│   ├── reports/                     # 每日报告 (YYYY-MM-DD.md / .json)
│   └── token_usage/                 # Token使用记录 (YYYY-MM-DD.json)
├── .github/workflows/
│   └── daily_report.yml             # GitHub Actions 每日自动运行
├── requirements.txt
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.12+
- DeepSeek API Key ([获取地址](https://platform.deepseek.com/))
- Telegram Bot Token + Chat ID ([BotFather](https://t.me/botfather))

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

支持两种方式配置环境变量：

**方式一：.env 文件（推荐本地开发）**

在项目根目录创建 `.env` 文件：

```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
TELEGRAM_BOT_TOKEN=1234567890:xxxxxxxxxx
TELEGRAM_CHAT_ID=-100xxxxxxxxxx
```

程序启动时会自动加载 `.env` 文件（使用 python-dotenv）。

**方式二：系统环境变量**

```bash
export DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxx"
export TELEGRAM_BOT_TOKEN="1234567890:xxxxxxxxxx"
export TELEGRAM_CHAT_ID="-100xxxxxxxxxx"
```

> 注意：`.env` 文件已配置在 `.gitignore` 中，不会被提交到 Git 仓库，确保敏感信息安全。

### 4. 自定义配置

- **新闻源**：编辑 `config/sources.yaml`，添加/删除 RSS 源
- **模型参数**：编辑 `config/models.yaml`，调整模型、温度、Prompt模板
- **定时时间**：编辑 `.github/workflows/daily_report.yml` 中的 `cron` 表达式

### 5. 本地运行

```bash
python main.py
```

运行后检查：
- `data/reports/YYYY-MM-DD.md` — Markdown格式日报
- `data/reports/YYYY-MM-DD.json` — 结构化数据
- `data/token_usage/YYYY-MM-DD.json` — Token消耗明细
- Telegram 频道/群组收到的推送消息

## GitHub Actions

### 设置 Secrets

在仓库 Settings → Secrets and variables → Actions 中添加：

| Secret | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 目标Chat ID |

### 运行策略

- **定时触发**：北京时间每日 14:30 (UTC 6:30)
- **手动触发**：GitHub Actions → Daily News Analysis → Run workflow
- **自动提交**：生成的报告和Token记录会自动 commit 回仓库

## 输出说明

### Markdown 日报包含：

- 📰 今日要闻摘要（按重要性排序）
- 🇺🇸 美股市场影响（趋势判断 + 逻辑分析）
- 🇨🇳 A股市场影响（趋势判断 + 逻辑分析）
- 🟢 利多行业（受益行业 + 受益逻辑）
- 🔴 利空行业（受损行业 + 受损逻辑）
- 🇺🇸 相关美股（个股代码 + 关联逻辑 + 置信度）
- 🇨🇳 相关A股（个股名称代码 + 关联逻辑 + 置信度）

### Token 消耗记录：

- 每个分析步骤的 input/output token 数量
- API调用耗时
- 美元成本计算（基于DeepSeek-V3官方定价）

## 成本估算

DeepSeek-V3 定价：
- 输入：$0.27 / 百万 token
- 输出：$1.10 / 百万 token

每次日报预计消耗 ~20,000-40,000 tokens，日均成本约 $0.01-0.02。

## 免责声明

本系统由 AI 自动生成分析内容，仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。
