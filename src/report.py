"""报告生成模块 - 生成 Markdown 和 JSON 格式的每日分析报告"""

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from .paths import get_path

logger = logging.getLogger(__name__)


def _format_section(title: str, content: str = "") -> str:
    """生成一个 markdown 章节标题"""
    return f"\n## {title}\n\n{content}"


def _format_bullet(items: List[str]) -> str:
    """将字符串列表格式化为 markdown bullet points"""
    return "\n".join(f"- {item}" for item in items)


def _format_sectors(sectors: List[Dict]) -> str:
    """格式化行业板块列表"""
    if not sectors:
        return "_暂无数据_"
    lines = []
    for s in sectors:
        sector = s.get("sector", "未知行业")
        reason = s.get("reason", "")
        lines.append(f"- **{sector}**: {reason}")
    return "\n".join(lines)


def _format_stocks(stocks: List[Dict]) -> str:
    """格式化个股列表"""
    if not stocks:
        return "_暂无数据_"
    lines = []
    for s in stocks:
        symbol = s.get("symbol", "")
        name = s.get("name", "")
        direction = s.get("direction", "neutral")
        confidence = s.get("confidence", 0)
        reason = s.get("reason", "")

        emoji = "🟢" if direction == "bullish" else "🔴" if direction == "bearish" else "⚪"
        label = "利好" if direction == "bullish" else "利空" if direction == "bearish" else "中性"
        display_name = f"{symbol} {name}".strip()
        lines.append(f"- {emoji} **{display_name}** ({label}, 置信度{confidence}%)\n  _{reason}_")
    return "\n".join(lines)


def generate_markdown(analysis: Dict, report_date: str, token_info: Optional[Dict] = None) -> str:
    """生成 Markdown 格式的日报"""
    sections = []

    # 标题
    #sections.append(f"# 📊 Horizon 每日金融分析报告\n\n**日期**: {report_date}\n")
    sections.append(f"**日期**: {report_date}\n")

    # 新闻摘要
    summaries = analysis.get("summaries", [])
    if isinstance(summaries, list):
        summary_lines = []
        for i, s in enumerate(summaries, 1):
            if isinstance(s, dict):
                title = s.get("title", f"新闻{i}")
                content = s.get("content", s.get("summary", ""))
                category = s.get("category", "")
                category_tag = f" `[{category}]`" if category else ""
                summary_lines.append(f"{i}. **{title}**{category_tag}\n   {content}")
            else:
                summary_lines.append(f"{i}. {s}")
        sections.append(_format_section("📰 今日要闻", "\n".join(summary_lines)))
    elif isinstance(summaries, dict) and "raw_output" not in summaries:
        sections.append(_format_section("📰 今日要闻", json.dumps(summaries, ensure_ascii=False, indent=2)))

    # 美股影响
    us = analysis.get("us_market", {})
    if us:
        trend_map = {"bullish": "📈 看涨", "bearish": "📉 看跌", "neutral": "📊 中性振荡"}
        trend = trend_map.get(us.get("trend", "neutral"), us.get("trend", ""))
        confidence = us.get("confidence", "N/A")
        reasons = us.get("reasons", [])
        us_content = f"**趋势判断**: {trend} (置信度: {confidence}%)\n\n**逻辑分析**:\n"
        us_content += _format_bullet(reasons) if reasons else "_暂无分析_"
        sections.append(_format_section("🇺🇸 美股市场影响", us_content))

    # A股影响
    cn = analysis.get("cn_market", {})
    if cn:
        trend_map = {"bullish": "📈 看涨", "bearish": "📉 看跌", "neutral": "📊 中性振荡"}
        trend = trend_map.get(cn.get("trend", "neutral"), cn.get("trend", ""))
        confidence = cn.get("confidence", "N/A")
        reasons = cn.get("reasons", [])
        cn_content = f"**趋势判断**: {trend} (置信度: {confidence}%)\n\n**逻辑分析**:\n"
        cn_content += _format_bullet(reasons) if reasons else "_暂无分析_"
        sections.append(_format_section("🇨🇳 A股市场影响", cn_content))

    # 利多行业
    bullish_sectors = analysis.get("bullish_sectors", [])
    sections.append(_format_section("🟢 利多行业", _format_sectors(bullish_sectors)))

    # 利空行业
    bearish_sectors = analysis.get("bearish_sectors", [])
    sections.append(_format_section("🔴 利空行业", _format_sectors(bearish_sectors)))

    # 美股个股
    us_stocks = analysis.get("us_stocks", [])
    sections.append(_format_section("🇺🇸 相关美股", _format_stocks(us_stocks)))

    # A股个股
    cn_stocks = analysis.get("cn_stocks", [])
    sections.append(_format_section("🇨🇳 相关A股", _format_stocks(cn_stocks)))

    # 页脚 - Token 使用信息
    footer = f"\n---\n\n*本报告由 Horizon 自动化新闻分析系统生成于 {report_date}*\n"
    footer += "*AI生成内容仅供参考，不构成投资建议*\n"
    footer += "*https://github.com/minxinhkc-png/Horizon*\n"

    # 添加 Token 使用信息
    if token_info:
        footer += "\n**Token 使用统计**:\n"
        total_input = token_info.get("total_input_tokens", 0)
        total_output = token_info.get("total_output_tokens", 0)
        total_cost = token_info.get("total_cost_usd", 0)
        footer += f"- Input Tokens: {total_input:,}\n"
        footer += f"- Output Tokens: {total_output:,}\n"
        footer += f"- Total Cost: ${total_cost:.4f}\n"

    sections.append(footer)

    return "\n".join(sections)


def generate_json(analysis: Dict, report_date: str, meta: Dict = None) -> Dict:
    """生成 JSON 格式的结构化报告"""
    return {
        "meta": {
            "date": report_date,
            "generated_at": meta.get("generated_at", "") if meta else "",
            "news_count": meta.get("news_count", 0) if meta else 0,
            "sources_used": meta.get("sources_used", []) if meta else [],
        },
        "analysis": analysis,
    }


def generate_news_md(news_items: List[Dict], report_date: str) -> str:
    """生成原始新闻清单的 Markdown 报告"""
    sections = []

    # 标题
    sections.append(f"# 📰 Horizon 每日新闻收集报告\n\n**日期**: {report_date}\n")

    # 新闻统计
    sections.append(_format_section("📊 新闻统计", f"共收集到 {len(news_items)} 条新闻"))

    # 原始新闻列表
    news_lines = []
    for i, item in enumerate(news_items, 1):
        # Handle both NewsItem objects and dictionaries
        if hasattr(item, 'source'):
            source = item.source
            title = item.title.strip() if hasattr(item, 'title') else ""
            category = item.category if hasattr(item, 'category') else ""
        else:
            source = item.get("source", "未知来源")
            title = item.get("title", "").strip()
            category = item.get("category", "")

        category_tag = f" `[{category}]`" if category else ""

        if title:
            news_lines.append(f"{i}. 【{source}】**{title}**{category_tag}")

    if news_lines:
        sections.append(_format_section("📋 原始新闻清单", "\n".join(news_lines)))
    else:
        sections.append(_format_section("📋 原始新闻清单", "_暂无数据_"))

    # 页脚
    sections.append(
        f"\n---\n\n*本报告由 Horizon 自动化新闻分析系统生成于 {report_date}*\n"
        f"*包含原始新闻收集结果*\n"
    )

    return "\n".join(sections)


def save_report(
    analysis: Dict,
    report_date: str,
    output_dir: str = "data/reports",
    meta: Dict = None,
    news_items: List[Dict] = None,
    token_info: Optional[Dict] = None,
) -> tuple:
    """保存 Markdown 和 JSON 报告文件（文件名包含时间戳，不覆盖旧文件）"""
    dir_path = get_path(output_dir)
    os.makedirs(dir_path, exist_ok=True)

    # 生成时间戳用于文件名（格式：YYYY-MM-DD_HHMMSS）
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    file_prefix = f"{report_date}_{timestamp}"

    # 保存原始新闻清单
    if news_items:
        news_md_path = dir_path / f"{file_prefix}_news.md"
        news_md_content = generate_news_md(news_items, report_date)
        with open(news_md_path, "w", encoding="utf-8") as f:
            f.write(news_md_content)
        logger.info(f"Raw news report saved to {news_md_path}")

    # 保存分析报告（带 token 信息）
    md_path = dir_path / f"{file_prefix}.md"
    md_content = generate_markdown(analysis, report_date, token_info=token_info)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    logger.info(f"Analysis report saved to {md_path}")

    # 保存 JSON（包含 token 信息）
    json_path = dir_path / f"{file_prefix}.json"
    json_data = generate_json(analysis, report_date, meta)
    if token_info:
        json_data["token_usage"] = token_info
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON report saved to {json_path}")

    return str(md_path), str(json_path)
