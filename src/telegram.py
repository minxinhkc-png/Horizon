"""Telegram推送模块 - 使用 Telethon 发送消息到 Channel"""

import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel

logger = logging.getLogger(__name__)


def _get_credentials() -> tuple:
    """从环境变量获取 Telegram 凭证"""
    api_id = os.environ.get("TG_API_ID", "").strip()
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    session_string = os.environ.get("TG_SESSION_STRING", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    logger.info(f"[TG Debug] api_id={api_id[:10]}... if exists: {bool(api_id)}")
    logger.info(f"[TG Debug] api_hash={api_hash[:10]}... if exists: {bool(api_hash)}")
    logger.info(f"[TG Debug] session_string length={len(session_string)}")
    logger.info(f"[TG Debug] chat_id={chat_id}, type={type(chat_id)}")

    if not api_id:
        raise ValueError("TG_API_ID environment variable is not set")
    if not api_hash:
        raise ValueError("TG_API_HASH environment variable is not set")
    if not session_string:
        raise ValueError("TG_SESSION_STRING environment variable is not set")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID environment variable is not set")

    # 移除可能存在的引号
    chat_id = chat_id.strip('"\'')

    # 转换为整数
    try:
        chat_id_int = int(chat_id)
        logger.info(f"[TG Debug] Parsed chat_id as int: {chat_id_int}")
    except ValueError as e:
        logger.error(f"[TG Debug] Failed to parse chat_id: {e}")
        raise ValueError(f"Invalid TELEGRAM_CHAT_ID: {chat_id}")

    return int(api_id), api_hash, session_string, chat_id_int


async def send_message_async(text: str, chat_id: int) -> bool:
    """使用 Telethon 异步发送消息到 Telegram Channel

    Args:
        text: 消息文本
        chat_id: Channel ID (格式: -100xxxxxxxxx)

    Returns:
        bool: 是否发送成功
    """
    api_id, api_hash, session_string, _ = _get_credentials()

    logger.info(f"[TG Debug] Creating Telegram client with api_id={api_id}")

    # 将 chat_id 转换为适合 Telethon 的格式
    # -100xxxxxxxxx 格式的 ID 需要提取出 channel_id
    # channel_id = abs(chat_id) - 1000000000000
    actual_chat_id = chat_id
    if chat_id < -1000000000000:
        # 这是一个超级群组/频道 ID
        actual_chat_id = abs(chat_id) - 1000000000000
        logger.info(f"[TG Debug] Converted channel ID: {chat_id} -> {actual_chat_id}")

    try:
        # 创建 Telethon 客户端
        client = TelegramClient(
            StringSession(session_string),
            api_id,
            api_hash
        )

        logger.info(f"[TG Debug] Starting client connection...")
        await client.start()
        logger.info("[TG Debug] Client started successfully")

        # 尝试多种方式获取实体
        entity = None
        error_msg = None

        # 方法1: 直接使用 PeerChannel
        try:
            entity = await client.get_entity(PeerChannel(channel_id=actual_chat_id))
            logger.info(f"[TG Debug] Method 1 - Found entity via PeerChannel: {entity.title if hasattr(entity, 'title') else entity}")
        except Exception as e1:
            error_msg = f"PeerChannel failed: {e1}"
            logger.warning(f"[TG Debug] Method 1 failed: {e1}")

        # 方法2: 直接使用 chat_id (Telethon 会自动识别)
        if entity is None:
            try:
                entity = await client.get_entity(chat_id)
                logger.info(f"[TG Debug] Method 2 - Found entity via direct chat_id: {entity}")
            except Exception as e2:
                error_msg += f"; Direct chat_id failed: {e2}"
                logger.warning(f"[TG Debug] Method 2 failed: {e2}")

        # 方法3: 遍历所有对话查找
        if entity is None:
            logger.info("[TG Debug] Method 3 - Searching through all dialogs...")
            async for dialog in client.iter_dialogs():
                if dialog.id == chat_id or dialog.id == -chat_id:
                    entity = dialog.entity
                    logger.info(f"[TG Debug] Method 3 - Found dialog: {dialog.name}, id={dialog.id}")
                    break

        # 方法4: 尝试使用字符串形式的 username（如果有的话）
        if entity is None:
            try:
                # 尝试直接作为数字 ID 获取
                entity = await client.get_entity(actual_chat_id)
                logger.info(f"[TG Debug] Method 4 - Found entity via actual_chat_id: {entity}")
            except Exception as e4:
                error_msg += f"; Actual chat_id failed: {e4}"
                logger.warning(f"[TG Debug] Method 4 failed: {e4}")

        if entity is None:
            logger.error(f"[TG Debug] All methods failed to find entity. Errors: {error_msg}")
            # 打印所有对话供参考
            logger.info("[TG Debug] Listing all accessible dialogs:")
            async for dialog in client.iter_dialogs(limit=10):
                logger.info(f"[TG Debug]   - {dialog.name} (id={dialog.id}, type={type(dialog.entity).__name__})")

            await client.disconnect()
            return False

        # 发送消息
        logger.info(f"[TG Debug] Sending message to entity: {entity.title if hasattr(entity, 'title') else entity}")
        await client.send_message(entity, text)
        logger.info(f"[TG Debug] Message sent successfully to channel {chat_id}")

        await client.disconnect()
        logger.info("[TG Debug] Client disconnected")
        return True

    except Exception as e:
        logger.error(f"[TG Debug] Exception in send_message_async: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"[TG Debug] Traceback: {traceback.format_exc()}")
        return False


def send_long_message(
    text: str,
    max_length: int = 4096,
) -> bool:
    """发送长消息（自动分段）- 同步包装器

    Args:
        text: 消息文本
        max_length: Telegram 单条消息最大长度

    Returns:
        bool: 是否发送成功
    """
    _, _, _, chat_id = _get_credentials()

    # 如果消息较短，直接发送
    if len(text) <= max_length:
        return asyncio.run(send_message_async(text, chat_id))

    # 消息过长，分段发送
    logger.info(f"Long message detected ({len(text)} chars), splitting into segments...")

    # 按段落分割
    paragraphs = text.split("\n\n")
    segments = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_length:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                segments.append(current)
            # 如果单个段落还是超长，强制切割
            if len(para) > max_length:
                for i in range(0, len(para), max_length - 100):
                    segments.append(para[i : i + max_length - 100])
                current = ""
            else:
                current = para

    if current:
        segments.append(current)

    # 发送所有分段
    success_count = 0
    total = len(segments)
    for i, seg in enumerate(segments, 1):
        try:
            if asyncio.run(send_message_async(seg, chat_id)):
                success_count += 1
            else:
                logger.warning(f"Failed to send segment {i}/{total}")
        except Exception as e:
            logger.error(f"Error sending segment {i}/{total}: {e}")

    logger.info(f"Telegram segments sent: {success_count}/{total}")
    return success_count > 0


def push_daily_report(markdown_content: str) -> bool:
    """推送每日分析报告到 Telegram

    Args:
        markdown_content: Markdown 格式的报告内容

    Returns:
        bool: 是否推送成功
    """
    logger.info("Pushing daily report to Telegram...")

    # 添加报告头信息
    header = f"🤖 *Horizon 每日金融分析报告*\n\n"

    if len(header) + len(markdown_content) > 4096:
        # 超长：先发头，再分段发正文
        try:
            _, _, _, chat_id = _get_credentials()
            logger.info(f"[TG Debug] Long message mode, chat_id={chat_id}")
            asyncio.run(send_message_async(header, chat_id))
        except Exception as e:
            logger.error(f"[TG Debug] Failed to send header: {e}")
        success = send_long_message(markdown_content)
    else:
        success = send_long_message(header + markdown_content)

    if success:
        logger.info("Daily report pushed to Telegram successfully")
    else:
        logger.error("Failed to push daily report to Telegram")

    return success


def send_error_notification(error_message: str) -> bool:
    """发送错误通知到 Telegram"""
    logger.info("Sending error notification to Telegram...")
    try:
        api_id, api_hash, session_string, chat_id = _get_credentials()
        logger.info(f"[TG Debug] Credentials loaded: api_id={api_id}, chat_id={chat_id}")
        text = f"⚠️ *Horizon 系统异常*\n\n```\n{error_message[:3000]}\n```"
        logger.info(f"[TG Debug] Error message length: {len(text)}")
        result = asyncio.run(send_message_async(text, chat_id))
        logger.info(f"[TG Debug] Send result: {result}")
        return result
    except Exception as e:
        logger.error(f"[TG Debug] Failed to send error notification: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"[TG Debug] Traceback: {traceback.format_exc()}")
        return False