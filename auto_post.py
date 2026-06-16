"""
自动发帖入口 —— 从 DeepSeek 读取创作内容，自动发布到脉脉

两种模式：
  ⚡ 闪电！  — 闪电观察者：读取热点话题帖子，按话题拆分+搜图，发到脉脉对应话题
  🔥 爆料！  — 爆料活动：读取爆料帖子，按编号拆分+提取图片，发到脉脉"我来爆个料"

前置条件：
  1. Chrome 带调试端口启动: python3 start_chrome.py
  2. 已登录 chat.deepseek.com 和 maimai.cn

用法：
  python3 auto_post.py lightning "职场爆料评论贴创作"          # 闪电模式
  python3 auto_post.py whistleblower "职场爆料评论贴创作"      # 爆料模式
  python3 auto_post.py lightning "热点话题" --dry-run         # 干跑模式
  python3 auto_post.py whistleblower "爆料对话" --limit 5     # 只发5篇
  python3 auto_post.py auto "职场爆料评论贴创作"              # 自动判断模式
"""

import json
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger

from config import settings, PROJECT_ROOT
from reader.deepseek_reader import DeepSeekReader
from parser.content_parser import ContentParser
from publisher.maimai import MaimaiPoster

# 状态文件路径
STATE_FILE = PROJECT_ROOT / ".post_state.json"


# ========== 日志 ==========

def setup_logger():
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
    )
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(
        str(log_dir / "auto_post_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{line} | {message}",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
    )


# ========== 状态管理 ==========

def load_state() -> Dict:
    """加载发布状态"""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except:
            return {}
    return {}


def save_state(state: Dict):
    """保存发布状态"""
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_last_index(state: Dict, conversation_name: str) -> int:
    """获取对话上次处理到的消息索引"""
    conv_state = state.get("conversations", {}).get(conversation_name, {})
    return conv_state.get("last_index", 0)


def update_last_index(state: Dict, conversation_name: str, index: int):
    """更新对话的消息索引"""
    if "conversations" not in state:
        state["conversations"] = {}
    if conversation_name not in state["conversations"]:
        state["conversations"][conversation_name] = {}
    state["conversations"][conversation_name]["last_index"] = index
    state["conversations"][conversation_name]["last_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)


# ========== 主流程 ==========

def run_lightning(
    conversation_name: str,
    dry_run: bool = False,
    limit: int = 0,
) -> bool:
    """
    ⚡ 闪电观察者模式

    流程：
      1. 读取 DeepSeek 对话中的新消息
      2. 按话题+第X篇拆分
      3. 为每个话题搜索配图
      4. 发布到脉脉对应话题
    """
    logger.info("=" * 55)
    logger.info("⚡ 闪电观察者模式")
    logger.info(f"   对话: {conversation_name}")
    logger.info(f"   干跑: {dry_run}")
    logger.info("=" * 55)

    # 加载状态
    state = load_state()
    last_index = get_last_index(state, conversation_name)

    # Step 1: 读取 DeepSeek 对话
    logger.info("📖 Step 1: 读取 DeepSeek 对话")
    reader = DeepSeekReader()
    if not reader.connect():
        return False
    if not reader.open_deepseek():
        reader.disconnect()
        return False
    if not reader.open_conversation(conversation_name):
        reader.disconnect()
        return False

    messages = reader.read_all_messages()
    reader.disconnect()

    # 只处理新消息（AI 回复）
    new_ai_messages = [
        m for m in messages
        if m['role'] == 'assistant' and m['index'] > last_index and m['content']
    ]

    if not new_ai_messages:
        logger.info("📭 没有新的 AI 回复")
        return True

    logger.success(f"✓ 找到 {len(new_ai_messages)} 条新 AI 回复")

    # Step 2: 解析内容
    logger.info("📝 Step 2: 解析帖子内容")
    parser = ContentParser()
    all_posts = []
    for msg in new_ai_messages:
        posts = parser.parse_lightning(msg['content'])
        all_posts.extend(posts)

    if not all_posts:
        logger.warning("❌ 没有解析出任何帖子")
        return False

    if limit > 0:
        all_posts = all_posts[:limit]

    logger.success(f"✓ 解析出 {len(all_posts)} 篇帖子")

    # Step 3: 搜图
    logger.info("🖼️  Step 3: 搜索配图")
    try:
        from searcher.image_searcher import ImageSearcher
        searcher = ImageSearcher()
        if searcher.connect():
            for post in all_posts:
                # 用话题名搜图
                topic = post.get('topic', '')
                if topic:
                    image_paths = searcher.search_and_download(topic, count=1)
                    post['image_paths'] = image_paths
                else:
                    post['image_paths'] = []
            searcher.disconnect()
        else:
            logger.warning("⚠️ 搜图器连接失败，跳过配图")
            for post in all_posts:
                post['image_paths'] = []
    except Exception as e:
        logger.warning(f"⚠️ 搜图失败: {e}，跳过配图")
        for post in all_posts:
            post['image_paths'] = []

    # Step 4: 预览
    logger.info("👀 Step 4: 预览帖子")
    for i, post in enumerate(all_posts, 1):
        logger.info(f"\n  [{i}/{len(all_posts)}] 话题: {post.get('topic', 'N/A')}")
        logger.info(f"    标题: {post.get('title', 'N/A')[:20]}")
        logger.info(f"    内容({len(post['content'])}字): {post['content'][:80]}...")
        logger.info(f"    配图: {len(post.get('image_paths', []))} 张")

    # Step 5: 发布到脉脉
    logger.info("🚀 Step 5: 发布到脉脉")
    poster = MaimaiPoster()
    if not poster.connect():
        logger.error("❌ 脉脉连接失败")
        return False

    try:
        result = poster.batch_post(
            posts=[
                {
                    "content": p['content'][:1000],
                    "title": p.get('title', '')[:20],
                    "image_paths": p.get('image_paths', []),
                    "topic": p.get('topic', '闪电观察者'),  # 用话题名作为脉脉话题
                }
                for p in all_posts
            ],
            interval=settings.maimai_post_interval,
            dry_run=dry_run,
        )
    except Exception as e:
        logger.error(f"❌ 批量发帖异常: {e}")
        poster.disconnect()
        return False

    poster.disconnect()

    # 更新状态
    if not dry_run:
        max_index = max(m['index'] for m in new_ai_messages)
        update_last_index(state, conversation_name, max_index)

    logger.info("=" * 55)
    logger.info(f"🏁 闪电模式完成: 成功 {result['success']}, 失败 {result['failed']}")
    logger.info("=" * 55)

    return result['failed'] == 0


def run_whistleblower(
    conversation_name: str,
    dry_run: bool = False,
    limit: int = 0,
) -> bool:
    """
    🔥 爆料活动模式

    流程：
      1. 读取 DeepSeek 对话中的新消息
      2. 按编号 1.2.3. 拆分
      3. 从用户消息中提取图片
      4. 发布到脉脉"我来爆个料"
    """
    logger.info("=" * 55)
    logger.info("🔥 爆料活动模式")
    logger.info(f"   对话: {conversation_name}")
    logger.info(f"   干跑: {dry_run}")
    logger.info("=" * 55)

    # 加载状态
    state = load_state()
    last_index = get_last_index(state, conversation_name)

    # Step 1: 读取 DeepSeek 对话
    logger.info("📖 Step 1: 读取 DeepSeek 对话")
    reader = DeepSeekReader()
    if not reader.connect():
        return False
    if not reader.open_deepseek():
        reader.disconnect()
        return False
    if not reader.open_conversation(conversation_name):
        reader.disconnect()
        return False

    messages = reader.read_all_messages()

    # ⚠️ 在断开连接前下载图片（需要浏览器 Cookie）
    logger.info("🖼️  下载消息中的图片...")
    downloaded_images = reader.download_all_images(messages)

    reader.disconnect()

    # 过滤新消息
    new_messages = [m for m in messages if m['index'] > last_index]

    if not new_messages:
        logger.info("📭 没有新消息")
        return True

    # Step 2: 将用户消息中的图片映射到对应的 AI 回复
    logger.info("🔗 Step 2: 关联用户图片与 AI 回复")
    new_ai_messages = []

    for msg in new_messages:
        if msg['role'] == 'assistant' and msg['content']:
            new_ai_messages.append(msg)

    if not new_ai_messages:
        logger.info("📭 没有新的 AI 回复")
        return True

    logger.success(f"✓ 找到 {len(new_ai_messages)} 条新 AI 回复")

    # Step 3: 解析内容 + 关联图片
    logger.info("📝 Step 3: 解析帖子内容")
    parser = ContentParser()
    all_posts = []

    # 建立图片关联：基于消息在 new_messages 列表中的位置
    # 用户消息的图片 → 紧跟其后的 AI 回复
    # 先构建 index → images 映射
    logger.debug(f"  downloaded_images: {downloaded_images}")
    logger.debug(f"  new_messages indices: {[m['index'] for m in new_messages]}")

    for msg in new_ai_messages:
        posts = parser.parse_whistleblower(msg['content'])
        # 关联图片：查找这条 AI 消息前面的用户消息是否有已下载的图片
        msg_images = []

        # 方法1：通过 index 差值匹配（同批次内 index 连续）
        for idx_key, paths in downloaded_images.items():
            if 0 < msg['index'] - idx_key <= 2:
                msg_images = paths
                logger.debug(f"  AI消息[{msg['index']}] 匹配到图片来源消息[{idx_key}], {len(paths)}张")
                break

        # 方法2：如果在 new_messages 列表中，AI 消息前一条是用户消息
        if not msg_images:
            for j, m in enumerate(new_messages):
                if m is msg and j > 0:
                    prev = new_messages[j - 1]
                    if prev['role'] == 'user' and prev['index'] in downloaded_images:
                        msg_images = downloaded_images[prev['index']]
                        logger.debug(f"  AI消息[{msg['index']}] 通过位置匹配到图片来源消息[{prev['index']}], {len(msg_images)}张")
                        break

        if msg_images:
            logger.info(f"  AI消息[{msg['index']}] 关联 {len(msg_images)} 张图片")

        for p in posts:
            p['image_paths'] = msg_images
        all_posts.extend(posts)

    if not all_posts:
        logger.warning("❌ 没有解析出任何帖子")
        return False

    if limit > 0:
        all_posts = all_posts[:limit]

    logger.success(f"✓ 解析出 {len(all_posts)} 篇帖子")

    # Step 4: 预览
    logger.info("👀 Step 4: 预览帖子")
    for i, post in enumerate(all_posts, 1):
        logger.info(f"\n  [{i}/{len(all_posts)}] 标题: {post.get('title', 'N/A')[:20]}")
        logger.info(f"    内容({len(post['content'])}字): {post['content'][:80]}...")
        logger.info(f"    图片: {len(post.get('image_paths', []))} 张")

    # Step 5: 发布到脉脉
    logger.info("🚀 Step 5: 发布到脉脉")
    poster = MaimaiPoster()
    if not poster.connect():
        logger.error("❌ 脉脉连接失败")
        return False

    try:
        result = poster.batch_post(
            posts=[
                {
                    "content": p['content'][:1000],
                    "title": p.get('title', '')[:20],
                    "image_paths": p.get('image_paths', []),
                    "topic": "我来爆个料",
                }
                for p in all_posts
            ],
            interval=settings.maimai_post_interval,
            dry_run=dry_run,
        )
    except Exception as e:
        logger.error(f"❌ 批量发帖异常: {e}")
        poster.disconnect()
        return False

    poster.disconnect()

    # 更新状态
    if not dry_run:
        max_index = max(m['index'] for m in new_messages)
        update_last_index(state, conversation_name, max_index)

    logger.info("=" * 55)
    logger.info(f"🏁 爆料模式完成: 成功 {result['success']}, 失败 {result['failed']}")
    logger.info("=" * 55)

    return result['failed'] == 0


def run_auto(
    conversation_name: str,
    dry_run: bool = False,
    limit: int = 0,
) -> bool:
    """
    自动判断模式：根据对话内容自动选择闪电/爆料模式
    """
    logger.info("🤖 自动判断模式...")

    # 读取消息并自动判断
    reader = DeepSeekReader()
    if not reader.connect():
        return False
    if not reader.open_deepseek():
        reader.disconnect()
        return False
    if not reader.open_conversation(conversation_name):
        reader.disconnect()
        return False

    messages = reader.read_all_messages()
    reader.disconnect()

    # 检查最近 AI 消息的内容格式
    ai_messages = [m for m in messages if m['role'] == 'assistant' and m['content']]
    if not ai_messages:
        logger.warning("没有 AI 消息可分析")
        return False

    parser = ContentParser()
    latest = ai_messages[-1]['content']

    has_topic_header = bool(re.search(r'^#{1,3}\s+.+', latest, re.MULTILINE)) if latest else False
    has_article_marker = bool(re.search(r'[第][一二三四五六七八九十\d]+[篇｜|]', latest)) if latest else False

    if has_topic_header and has_article_marker:
        logger.info("🤖 判断为 ⚡ 闪电观察者模式")
        return run_lightning(conversation_name, dry_run, limit)
    else:
        logger.info("🤖 判断为 🔥 爆料活动模式")
        return run_whistleblower(conversation_name, dry_run, limit)


# ========== 入口 ==========

if __name__ == "__main__":
    setup_logger()

    import argparse
    import re

    parser_cli = argparse.ArgumentParser(description="自动发帖助手")
    parser_cli.add_argument(
        "mode",
        choices=["lightning", "whistleblower", "auto"],
        help="模式: lightning(闪电) / whistleblower(爆料) / auto(自动判断)",
    )
    parser_cli.add_argument(
        "conversation",
        help="DeepSeek 对话名称（支持模糊匹配）",
    )
    parser_cli.add_argument("--dry-run", action="store_true", help="干跑模式，不点击发布")
    parser_cli.add_argument("--limit", type=int, default=0, help="最多发几篇（0=不限）")

    args = parser_cli.parse_args()

    if args.mode == "lightning":
        success = run_lightning(args.conversation, args.dry_run, args.limit)
    elif args.mode == "whistleblower":
        success = run_whistleblower(args.conversation, args.dry_run, args.limit)
    else:
        success = run_auto(args.conversation, args.dry_run, args.limit)

    sys.exit(0 if success else 1)
