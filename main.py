"""Horizon 自动化新闻分析系统 - 主入口

编排全流程：抓取 → 分析 → 报告生成 → 保存 → Telegram推送 → Token记录
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 文件（优先级：项目根目录 .env > 系统环境变量）
load_dotenv(Path(__file__).parent / ".env")

from src.fetcher import fetch_all_news, format_news_for_analysis
from src.analyzer import DeepSeekAnalyzer
from src.report import save_report
from src.telegram import push_daily_report, send_error_notification
from src.token_tracker import TokenTracker

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("horizon")


def main():
    """主流程"""
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"Horizon Daily Analysis - {today}")
    logger.info("=" * 60)

    # ---- Step 1: 抓取新闻 ----
    logger.info("[1/5] Fetching news from all sources...")
    try:
        news_items = fetch_all_news()
        if not news_items:
            logger.warning("No news items fetched! Check sources or network.")
            send_error_notification(
                f"{today}: No news items fetched from any source. "
                "Please check network connectivity and RSS feed availability."
            )
            return
        logger.info(f"Fetched {len(news_items)} unique news items")
    except Exception as e:
        logger.error(f"News fetching failed: {e}")
        send_error_notification(f"{today}: News fetching error: {str(e)[:1000]}")
        return

    # 格式化为分析文本
    news_text = format_news_for_analysis(news_items)
    logger.info(f"Formatted news text: {len(news_text)} characters")

    # ---- Step 2: DeepSeek 分析 ----
    logger.info("[2/5] Starting DeepSeek analysis (3-step pipeline)...")
    tracker = TokenTracker()

    try:
        analyzer = DeepSeekAnalyzer(tracker=tracker)
        analysis = analyzer.analyze_news(news_text)
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        send_error_notification(f"{today}: Config error: {str(e)[:1000]}")
        return
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        send_error_notification(f"{today}: DeepSeek analysis error: {str(e)[:1000]}")
        return

    # ---- Step 3: 生成并保存报告 ----
    logger.info("[3/5] Generating reports...")
    try:
        # 先获取 token 使用信息
        token_info = tracker.get_summary()["summary"]
        logger.info(f"Token info: input={token_info['total_input_tokens']}, output={token_info['total_output_tokens']}, cost=${token_info['total_cost_usd']:.4f}")

        meta = {
            "generated_at": datetime.now().isoformat(),
            "news_count": len(news_items),
            "sources_used": list(set(item.source for item in news_items)),
        }
        md_path, json_path = save_report(analysis, today, meta=meta, news_items=news_items, token_info=token_info)
        logger.info(f"Reports saved: {md_path}, {json_path}")
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        send_error_notification(f"{today}: Report generation error: {str(e)[:1000]}")
        return

    # ---- Step 4: 保存 Token 记录 ----
    logger.info("[4/5] Saving token usage records...")
    try:
        token_path = tracker.save(today)
        logger.info(f"Token usage saved: {token_path}")
    except Exception as e:
        logger.error(f"Token tracking save failed: {e}")

    # ---- Step 5: Telegram 推送 ----
    logger.info("[5/5] Pushing daily report to Telegram...")
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        push_daily_report(md_content)
    except Exception as e:
        logger.error(f"Telegram push failed: {e}")

    # ---- 完成 ----
    cost = tracker.compute_cost()
    logger.info("=" * 60)
    logger.info(f"Horizon Daily Analysis completed for {today}")
    logger.info(f"   News items: {len(news_items)}")
    logger.info(f"   Token cost: ${cost['total_cost_usd']}")
    logger.info(f"   Reports: {md_path}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()