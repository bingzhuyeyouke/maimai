"""
测试 DeepSeek 读取器 + 内容解析器

验证从 DeepSeek 网页端读取对话并正确拆分为帖子的完整流程
"""

import json
import time
import sys
from loguru import logger

from config import settings, PROJECT_ROOT
from reader.deepseek_reader import DeepSeekReader
from parser.content_parser import ContentParser


def setup_logger():
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
    )


def test_reader():
    """测试 DeepSeek 读取器"""
    logger.info("=" * 60)
    logger.info("📋 测试 1: DeepSeek 对话读取")
    logger.info("=" * 60)

    reader = DeepSeekReader()

    if not reader.connect():
        logger.error("❌ Chrome 连接失败")
        return None

    if not reader.open_deepseek():
        logger.error("❌ DeepSeek 打开失败")
        reader.disconnect()
        return None

    # 先列出相关对话
    conversations = reader.list_conversations(keyword="爆料")
    logger.info(f"\n包含'爆料'的对话:")
    for c in conversations[:5]:
        logger.info(f"  • {c['name']}")

    # 打开第一个爆料对话
    if not conversations:
        logger.error("❌ 没有找到爆料相关对话")
        reader.disconnect()
        return None

    target = conversations[0]['name']
    if not reader.open_conversation(target):
        logger.error(f"❌ 无法打开对话: {target}")
        reader.disconnect()
        return None

    # 读取所有消息
    messages = reader.read_all_messages()

    # 打印消息摘要
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 消息摘要")
    logger.info(f"{'='*60}")

    for msg in messages:
        icon = "👤" if msg['role'] == 'user' else "🤖"
        images_info = f" 🖼️{len(msg['images'])}" if msg['images'] else ""
        logger.info(f"  [{msg['index']}] {icon} ({len(msg['content'])}字{images_info}): {msg['content'][:80]}...")
        if msg['images']:
            for img_url in msg['images']:
                logger.info(f"      🖼️ {img_url[:80]}")

    reader.disconnect()
    return messages


def test_parser(messages):
    """测试内容解析器"""
    if not messages:
        logger.warning("没有消息可解析")
        return

    logger.info(f"\n{'='*60}")
    logger.info("📋 测试 2: 内容解析（爆料模式）")
    logger.info(f"{'='*60}")

    parser = ContentParser()

    # 提取所有 AI 消息
    ai_messages = [m for m in messages if m['role'] == 'assistant']
    logger.info(f"AI 消息数: {len(ai_messages)}")

    for i, msg in enumerate(ai_messages):
        logger.info(f"\n--- AI 消息 {i+1} ({len(msg['content'])}字) ---")
        logger.info(f"  前100字: {msg['content'][:100]}...")

        # 自动判断模式
        posts = parser.parse_auto(msg['content'])

        logger.info(f"  解析结果: {len(posts)} 篇帖子")
        for p in posts:
            logger.info(f"    [{p['index']}] 话题={p.get('topic', 'N/A')} 标题={p.get('title', 'N/A')[:20]}")
            logger.info(f"        内容预览: {p['content'][:60]}...")


def test_lightning_parser():
    """测试闪电观察者解析（用模拟数据）"""
    logger.info(f"\n{'='*60}")
    logger.info("📋 测试 3: 闪电观察者解析（模拟数据）")
    logger.info(f"{'='*60}")

    parser = ContentParser()

    sample_text = """
## 巴西队被吐槽已成一人球队

**第一篇｜大罗小罗看到这场比赛估计得关电视**

6月14日巴西对阵巴拉圭，全场比赛看下来就一个字：累。不是球员累，是看球的累。维尼修斯一个人在左路突突突，其他人仿佛在看戏。

最离谱的是中场，连个能传出威胁球的人都没有，全靠维尼修斯回撤拿球自己干。这还是五星巴西？大罗小罗看到估计得关电视。

**第二篇｜内马尔之后巴西再无10号**

巴西足球的衰落不是一天两天了，但直到今天才真正让人绝望。内马尔离开之后，巴西连个像样的10号都找不出来。

看看隔壁阿根廷，梅西老了还有迪巴拉、恩佐。巴西呢？维尼修斯是边锋，罗德里戈也是边锋，帕奎塔是工兵。10号位的传承，在巴西已经断了。

## 腾讯收购喜马拉雅

**第一篇｜互联网音频终局来了**

腾讯收购喜马拉雅的消息终于落锤，互联网音频市场基本到了终局。喜马拉雅作为头部玩家，最终还是没逃过被收购的命运。

从商业角度看，这波操作腾讯赚了。音频赛道的护城河比视频深，喜马拉雅的用户粘性是实打实的。

**第二篇｜小公司的宿命**

喜马拉雅的结局，再次印证了一个残酷的事实：在互联网大厂面前，独立平台越来越难生存。
"""

    posts = parser.parse_lightning(sample_text)
    logger.info(f"解析结果: {len(posts)} 篇帖子")
    for p in posts:
        logger.info(f"  [{p['index']}] 话题={p['topic']}")
        logger.info(f"      标题={p['title']}")
        logger.info(f"      内容预览: {p['content'][:60]}...")


def test_whistleblower_parser():
    """测试爆料活动解析（用模拟数据）"""
    logger.info(f"\n{'='*60}")
    logger.info("📋 测试 4: 爆料活动解析（模拟数据）")
    logger.info(f"{'='*60}")

    parser = ContentParser()

    sample_text = """
1. 快手员工爆料：电商为了搞人走无下限
快手员工爆料：快手电商真是无下限，为了把人搞走什么恶心的招都使出来。评论说帮助维权都没用，HR比法务还专业。

2. 美团员工问：美团有团团伙伙、山头主义吗
美团员工爆料：我们美团有团团伙伙，你一团我一伙，拉帮结派，山头主义吗？评论说这叫组织能力，不叫山头主义。

3. 某大厂员工：年终奖取消后更卷了
某大厂员工爆料：取消年终奖之后大家更卷了，因为都不知道还能靠什么拿到钱。以前还能躺平拿年终，现在连这个盼头都没了。
"""

    posts = parser.parse_whistleblower(sample_text)
    logger.info(f"解析结果: {len(posts)} 篇帖子")
    for p in posts:
        logger.info(f"  [{p['index']}] 标题={p.get('title', 'N/A')[:20]}")
        logger.info(f"      内容预览: {p['content'][:60]}...")


if __name__ == "__main__":
    setup_logger()

    # 测试1: 真实对话读取
    messages = test_reader()

    # 测试2: 解析真实对话
    if messages:
        test_parser(messages)

    # 测试3: 闪电观察者模拟数据
    test_lightning_parser()

    # 测试4: 爆料活动模拟数据
    test_whistleblower_parser()

    logger.info(f"\n{'='*60}")
    logger.info("🏁 所有测试完成")
    logger.info(f"{'='*60}")
