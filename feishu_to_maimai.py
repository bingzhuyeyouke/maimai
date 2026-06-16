"""
飞书表格 → 脉脉自动发帖

功能：
  1. 从飞书多维表格读取待发布的帖子（文字+图片）
  2. 下载飞书图片到本地
  3. 自动在脉脉发布帖子（填文字+上传图片+添加话题）
  4. 每篇间隔3分钟，避免平台检测
  5. 更新飞书表格状态（已发布/失败）

触发方式：
  向 Claude 说"发帖！"

飞书表格结构（建议）：
  | A: 序号 | B: 帖子内容 | C: 图片 | D: 状态 | E: 发布时间 | F: 备注 |
  状态值：待发布 / 已发布 / 失败

用法：
  终端1：python3 start_chrome.py                    # 先启动 Chrome
  终端2：python3 feishu_to_maimai.py                 # 运行全流程
  终端2：python3 feishu_to_maimai.py --dry-run       # 干跑模式
  终端2：python3 feishu_to_maimai.py --limit 3        # 只发3篇
"""

import sys
from loguru import logger

from config import settings, PROJECT_ROOT
from integrator.feishu import FeishuReader
from publisher.maimai import MaimaiPoster


# ========== 日志 ==========

def setup_logger():
    """配置日志"""
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
    )
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(
        str(log_dir / "feishu_to_maimai_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{line} | {message}",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
    )


# ========== 主流程 ==========

def run(dry_run: bool = False, limit: int = 0) -> bool:
    """
    执行飞书→脉脉发帖流程

    参数:
        dry_run: 干跑模式，填好内容不点发布
        limit:   最多发几篇（0=不限）

    返回:
        True 全部成功，False 有失败
    """
    logger.info("=" * 55)
    logger.info("📝 飞书→脉脉自动发帖流程启动")
    logger.info(f"   干跑模式: {dry_run}")
    logger.info(f"   发帖间隔: {settings.maimai_post_interval} 秒")
    logger.info("=" * 55)

    # ===== 第1步：读取飞书表格 =====
    logger.info("📊 第1步：读取飞书表格")
    reader = FeishuReader()

    if not reader.connect():
        logger.error("❌ 飞书连接失败，请检查 .env 中的 FEISHU_APP_ID/SECRET")
        return False

    posts = reader.read_pending_posts()

    if not posts:
        logger.info("📭 没有待发布的帖子")
        return True

    # 限制数量
    if limit > 0:
        logger.info(f"   限制发布数量: {limit}/{len(posts)}")
        posts = posts[:limit]

    logger.success(f"✓ 读取到 {len(posts)} 篇待发布帖子")

    # ===== 第2步：下载图片 =====
    logger.info("🖼️  第2步：下载飞书图片")
    for post in posts:
        if post["image_tokens"]:
            local_paths = reader.download_images(
                post["image_tokens"],
                post_id=post["row_id"],
            )
            post["image_paths"] = local_paths
        else:
            post["image_paths"] = []

    # ===== 第3步：连接 Chrome =====
    logger.info("🔗 第3步：连接 Chrome")
    poster = MaimaiPoster()

    if not poster.connect():
        logger.error("❌ Chrome 连接失败，请确保已启动 Chrome（python3 start_chrome.py）")
        return False

    # ===== 第4步：批量发帖 =====
    logger.info("🚀 第4步：批量发帖到脉脉")
    try:
        result = poster.batch_post(
            posts=posts,
            interval=settings.maimai_post_interval,
            dry_run=dry_run,
        )
    except Exception as e:
        logger.error(f"❌ 批量发帖异常: {e}")
        poster.disconnect()
        return False

    poster.disconnect()

    # ===== 第5步：更新飞书表格状态 =====
    logger.info("📋 第5步：更新飞书表格状态")
    for i, post in enumerate(posts):
        if i < len(result["results"]):
            status = result["results"][i]["status"]
            if status == "success":
                reader.mark_as_published(post["row_id"])
            else:
                reader.mark_as_failed(post["row_id"], "发帖失败")

    # 汇总
    logger.info("=" * 55)
    logger.info(f"🏁 发帖流程结束: 成功 {result['success']}, 失败 {result['failed']}")
    logger.info("=" * 55)

    return result["failed"] == 0


# ========== 入口 ==========

if __name__ == "__main__":
    setup_logger()

    import argparse
    parser = argparse.ArgumentParser(description="飞书→脉脉自动发帖")
    parser.add_argument("--dry-run", action="store_true", help="干跑模式，不点击发布")
    parser.add_argument("--limit", type=int, default=0, help="最多发几篇（0=不限）")
    args = parser.parse_args()

    success = run(dry_run=args.dry_run, limit=args.limit)
    sys.exit(0 if success else 1)
