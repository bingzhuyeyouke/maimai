"""
批量预存发帖 — 图片+文章预存到文件夹，分组批量发到脉脉

用法：
  # 发全部50篇（每10篇一组，组间休息5分钟）
  python3 batch_post.py

  # 只发第1-10篇
  python3 batch_post.py --start 1 --end 10

  # 从第21篇继续（之前1-20已发完）
  python3 batch_post.py --start 21

  # 干跑预览
  python3 batch_post.py --dry-run

  # 指定文章和图片目录
  python3 batch_post.py --articles posts/batch/articles.txt --images posts/batch/images

文件结构：
  posts/batch/
  ├── articles.txt      ← 50篇文章（1. 标题：xxx / 正文：xxx 格式）
  └── images/
      ├── 1.png         ← 第1篇的配图
      ├── 2.png         ← 第2篇的配图
      ├── ...
      └── 50.png        ← 第50篇的配图

发帖规则：
  - 每10篇一组（1-10, 11-20, 21-30, 31-40, 41-50）
  - 组内间隔：2-3分钟（150秒±30秒随机）
  - 组间休息：5分钟
  - 话题：我来爆个料
  - 标题填入帖子标题栏

前置条件：
  1. Chrome 带调试端口启动: python3 start_chrome.py
  2. 已登录脉脉
"""

import re
import sys
import time
import random
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger

from config import settings, PROJECT_ROOT
from publisher.maimai import MaimaiPoster


# ========== 日志 ==========

def setup_logger():
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
    )


# ========== 解析文章 ==========

def parse_articles(text: str) -> List[Dict]:
    """
    解析批量文章，格式同 paste_post.py：
      1. 标题：xxx
      正文：xxx

      2. 标题：xxx
      正文：xxx
    """
    posts = []

    # 匹配编号+标题+正文
    pattern = re.compile(
        r'(?:^|\n)\s*(\d+)\.\s*标题[：:]\s*(.+?)(?:\n\s*正文[：:]\s*(.+?))?(?=\n\s*\d+\.\s*标题[：:]|\Z)',
        re.DOTALL,
    )
    matches = list(pattern.finditer(text))

    if matches:
        for m in matches:
            title = m.group(2).strip()[:20]
            content = (m.group(3) or '').strip()[:1000]
            if not content:
                content = title
            posts.append({
                'index': int(m.group(1)),
                'title': title,
                'content': content,
                'topic': '我来爆个料',
                'image_paths': [],
            })
        return posts

    # 备用：用分隔符拆分
    chunks = re.split(r'\n[-=]{3,}\n', text)
    if len(chunks) > 1:
        for i, chunk in enumerate(chunks, 1):
            chunk = chunk.strip()
            if not chunk:
                continue
            lines = chunk.split('\n')
            first_line = re.sub(r'^\d+\.\s*', '', lines[0].strip())
            posts.append({
                'index': i,
                'title': first_line[:20],
                'content': chunk[:1000],
                'topic': '我来爆个料',
                'image_paths': [],
            })
        return posts

    # 兜底
    if text.strip():
        first_line = text.strip().split('\n')[0][:20]
        posts.append({
            'index': 1,
            'title': first_line,
            'content': text.strip()[:1000],
            'topic': '我来爆个料',
            'image_paths': [],
        })

    return posts


# ========== 图片配对 ==========

def _natural_sort_key(s: str) -> list:
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


def pair_images(posts: List[Dict], image_dir: str):
    """
    按序号配对图片：1.png→第1篇, 2.png→第2篇...
    支持 jpg/png/jpeg/gif/webp
    """
    img_path = Path(image_dir)
    if not img_path.exists():
        logger.warning(f"⚠️ 图片目录不存在: {image_dir}")
        return

    all_images = sorted([
        f for f in img_path.iterdir()
        if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp')
    ], key=lambda f: _natural_sort_key(f.stem))

    if not all_images:
        logger.warning(f"⚠️ 图片目录为空: {image_dir}")
        return

    logger.info(f"📷 找到 {len(all_images)} 张图片")

    for i, post in enumerate(posts):
        idx = post.get('index', i + 1) - 1  # 文章序号从1开始，图片索引从0开始
        if idx < len(all_images):
            post['image_paths'] = [str(all_images[idx])]
            logger.info(f"  📎 {all_images[idx].name} → 第{post['index']}篇")
        elif i < len(all_images):
            # 按文件排序顺序配对
            post['image_paths'] = [str(all_images[i])]
            logger.info(f"  📎 {all_images[i].name} → 第{post['index']}篇")
        else:
            logger.warning(f"  ⚠️ 第{post['index']}篇没有配对图片")


# ========== 分组发帖 ==========

def batch_run(
    articles_path: str = None,
    image_dir: str = None,
    start: int = 1,
    end: int = 0,
    group_size: int = 10,
    dry_run: bool = False,
):
    """批量预存发帖主流程"""
    logger.info("=" * 55)
    logger.info("📦 批量预存发帖模式")
    logger.info("=" * 55)

    # 默认路径
    if not articles_path:
        articles_path = str(PROJECT_ROOT / 'posts' / 'batch' / 'articles.txt')
    if not image_dir:
        image_dir = str(PROJECT_ROOT / 'posts' / 'batch' / 'images')

    # 读取文章
    logger.info(f"📄 读取文章: {articles_path}")
    text = Path(articles_path).read_text(encoding='utf-8')
    posts = parse_articles(text)

    if not posts:
        logger.error("❌ 没有解析出任何文章")
        return False

    logger.success(f"✓ 解析出 {len(posts)} 篇文章")

    # 配对图片
    pair_images(posts, image_dir)

    # 筛选范围
    if start > 1:
        posts = [p for p in posts if p['index'] >= start]
        logger.info(f"📋 从第 {start} 篇开始")

    if end > 0:
        posts = [p for p in posts if p['index'] <= end]
        logger.info(f"📋 到第 {end} 篇结束")

    if not posts:
        logger.error("❌ 筛选后没有文章")
        return False

    # 分组
    total = len(posts)
    groups = [posts[i:i + group_size] for i in range(0, total, group_size)]

    logger.info(f"📊 共 {total} 篇，分 {len(groups)} 组（每组{group_size}篇）")
    for gi, group in enumerate(groups, 1):
        first, last = group[0]['index'], group[-1]['index']
        img_count = sum(1 for p in group if p.get('image_paths'))
        logger.info(f"  第{gi}组: 第{first}-{last}篇, {img_count}/{len(group)}篇有配图")

    # 预览
    for i, post in enumerate(posts, 1):
        logger.info(f"\n  [{i}/{total}] 第{post['index']}篇")
        logger.info(f"    标题: {post['title'][:20]}")
        logger.info(f"    正文({len(post['content'])}字): {post['content'][:60]}...")
        logger.info(f"    图片: {len(post.get('image_paths', []))} 张")

    if dry_run:
        logger.info("\n🔍 干跑模式：内容已解析，但不发帖")
        return True

    # 连接 Chrome
    logger.info("🚀 开始发布到脉脉...")
    poster = MaimaiPoster()
    if not poster.connect():
        logger.error("❌ 连接 Chrome 失败")
        return False

    # 按组发帖
    total_success = 0
    total_failed = 0

    try:
        for gi, group in enumerate(groups, 1):
            first, last = group[0]['index'], group[-1]['index']
            logger.info(f"\n{'🔵' * 20}")
            logger.info(f"📦 第 {gi}/{len(groups)} 组: 第{first}-{last}篇")
            logger.info(f"{'🔵' * 20}")

            result = poster.batch_post(
                posts=[
                    {
                        "content": p['content'][:1000],
                        "title": p.get('title', '')[:20],
                        "image_paths": p.get('image_paths', []),
                        "topic": p.get('topic', '我来爆个料'),
                    }
                    for p in group
                ],
                interval=settings.maimai_post_interval,  # 150秒±30秒
                dry_run=dry_run,
            )

            total_success += result['success']
            total_failed += result['failed']

            # 组间休息（最后一组不等）
            if gi < len(groups):
                rest_time = 300  # 5分钟
                logger.info(f"\n☕ 第{gi}组完成，休息 {rest_time} 秒后发下一组...")
                time.sleep(rest_time)

    except Exception as e:
        logger.error(f"❌ 批量发帖异常: {e}")
        poster.disconnect()
        return False

    poster.disconnect()

    logger.info("\n" + "=" * 55)
    logger.info(f"🏁 全部完成: 成功 {total_success}, 失败 {total_failed}")
    logger.info("=" * 55)

    return total_failed == 0


# ========== 入口 ==========

if __name__ == "__main__":
    setup_logger()

    import argparse

    cli = argparse.ArgumentParser(description="批量预存发帖 — 图片+文章预存，分组批量发到脉脉")
    cli.add_argument("--articles", type=str, help="文章文件路径（默认 posts/batch/articles.txt）")
    cli.add_argument("--images", type=str, help="图片目录路径（默认 posts/batch/images/）")
    cli.add_argument("--start", type=int, default=1, help="从第几篇开始（默认1）")
    cli.add_argument("--end", type=int, default=0, help="到第几篇结束（默认全部）")
    cli.add_argument("--group-size", type=int, default=10, help="每组几篇（默认10）")
    cli.add_argument("--dry-run", action="store_true", help="干跑模式")

    args = cli.parse_args()

    success = batch_run(
        articles_path=args.articles,
        image_dir=args.images,
        start=args.start,
        end=args.end,
        group_size=args.group_size,
        dry_run=args.dry_run,
    )

    sys.exit(0 if success else 1)
