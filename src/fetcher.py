"""RSS新闻抓取模块 - 抓取、去重、清洗、过滤"""

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional

import feedparser
import yaml
from bs4 import BeautifulSoup

from .paths import get_path

logger = logging.getLogger(__name__)


class NewsItem:
    """单条新闻数据结构"""

    def __init__(
        self,
        title: str,
        link: str,
        content: str,
        source: str,
        category: str,
        language: str,
        published: Optional[datetime] = None,
    ):
        self.title = title
        self.link = link
        self.content = content
        self.source = source
        self.category = category
        self.language = language
        self.published = published

    @property
    def dedup_key(self) -> str:
        """用于去重的唯一键（基于 title+link 的 hash）"""
        raw = f"{self.title}|{self.link}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "link": self.link,
            "content": self.content,
            "source": self.source,
            "category": self.category,
            "language": self.language,
            "published": self.published.isoformat() if self.published else None,
        }


def load_sources_config(config_path: str = "config/sources.yaml") -> Dict:
    """加载新闻源配置"""
    path = get_path(config_path)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clean_html(html_text: str) -> str:
    """清洗HTML标签，提取纯文本"""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    # 移除script和style标签
    for tag in soup(["script", "style", "iframe", "img"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # 去除多余空行
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def parse_published_time(entry: Dict) -> Optional[datetime]:
    """解析RSS条目的发布时间"""
    # feedparser会将时间解析为时间元组存入 published_parsed 或 updated_parsed
    time_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
    if time_tuple:
        try:
            return datetime(*time_tuple[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    return None


def fetch_feed(
    source_config: Dict, timeout: int = 30, max_entries: int = 30
) -> List[NewsItem]:
    """从单个RSS源抓取新闻"""
    name = source_config["name"]
    url = source_config["url"]
    category = source_config.get("category", "general")
    language = source_config.get("language", "en")

    logger.info(f"Fetching feed: {name} ({url})")

    try:
        # feedparser不支持timeout参数，用全局设置替代
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            logger.warning(f"Feed {name} returned error: {feed.bozo_exception}")
            return []

        items = []
        for entry in feed.entries[:max_entries]:
            # 提取内容：优先 summary/detail，其次 description
            raw_content = entry.get("summary") or entry.get("description") or ""
            # 有些feed在content字段存放完整内容
            if "content" in entry:
                content_value = entry.content[0].get("value", "")
                if len(content_value) > len(raw_content):
                    raw_content = content_value

            content = clean_html(raw_content)
            title = clean_html(entry.get("title", ""))
            link = entry.get("link", "")

            if not title or not link:
                continue

            published = parse_published_time(entry)

            item = NewsItem(
                title=title,
                link=link,
                content=content,
                source=name,
                category=category,
                language=language,
                published=published,
            )
            items.append(item)

        logger.info(f"Feed {name}: fetched {len(items)} entries")
        return items

    except Exception as e:
        logger.warning(f"Failed to fetch {name}: {e}")
        return []


def filter_by_time(items: List[NewsItem], time_window_hours: int = 24) -> List[NewsItem]:
    """按时间窗口过滤，只保留最近N小时内的新闻"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)

    filtered = []
    for item in items:
        if item.published and item.published >= cutoff:
            filtered.append(item)
        elif not item.published:
            # 无发布时间的条目保留（可能解析失败）
            filtered.append(item)

    logger.info(
        f"Time filter: {len(items)} → {len(filtered)} entries (window={time_window_hours}h)"
    )
    return filtered


def deduplicate(items: List[NewsItem]) -> List[NewsItem]:
    """基于 title+link hash 去重"""
    seen = set()
    unique = []
    for item in items:
        key = item.dedup_key
        if key not in seen:
            seen.add(key)
            unique.append(item)
    removed = len(items) - len(unique)
    if removed > 0:
        logger.info(f"Deduplication: removed {removed} duplicate entries")
    return unique


def fetch_all_news(config_path: str = "config/sources.yaml") -> List[NewsItem]:
    """抓取所有配置的新闻源，执行去重和时间过滤"""
    config = load_sources_config(config_path)
    settings = config.get("fetch_settings", {})

    time_window = settings.get("time_window_hours", 24)
    max_entries = settings.get("max_entries_per_source", 30)
    timeout = settings.get("timeout", 30)
    continue_on_error = settings.get("continue_on_error", True)

    all_items: List[NewsItem] = []

    # 抓取国际源
    for source in config.get("international", []):
        items = fetch_feed(source, timeout=timeout, max_entries=max_entries)
        all_items.extend(items)

    # 抓取国内源
    for source in config.get("domestic", []):
        items = fetch_feed(source, timeout=timeout, max_entries=max_entries)
        all_items.extend(items)

    logger.info(f"Total raw entries: {len(all_items)}")

    # 时间过滤
    all_items = filter_by_time(all_items, time_window_hours=time_window)

    # 去重
    if settings.get("deduplication", True):
        all_items = deduplicate(all_items)

    logger.info(f"Final entries after filtering and dedup: {len(all_items)}")
    return all_items


def format_news_for_analysis(items: List[NewsItem]) -> str:
    """将新闻条目格式化为供LLM分析的文本"""
    sections = []
    for item in items:
        section = f"【{item.source}】{item.title}\n{item.content[:500]}"
        if item.content and len(item.content) > 500:
            section += "..."
        sections.append(section)

    return "\n\n".join(sections)