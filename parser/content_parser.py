"""
内容解析器 —— 将 DeepSeek 的长回复拆分为独立帖子

支持两种模式：
  1. ⚡ 闪电观察者：按「## 话题标题」+「**第一篇｜**」/「**第二篇｜**」拆分
  2. 🔥 爆料活动：按「1. 」「2. 」「3. 」编号拆分

用法：
    parser = ContentParser()
    posts = parser.parse_lightning(text)
    posts = parser.parse_whistleblower(text)
"""

import re
from typing import List, Dict, Optional
from loguru import logger


class ContentParser:
    """DeepSeek 回复内容拆分器"""

    def parse_lightning(self, text: str) -> List[Dict]:
        """
        解析闪电观察者内容

        格式特征：
          ## 话题标题
          **第一篇｜标题1**
          内容1...
          **第二篇｜标题2**
          内容2...

        返回:
            [{"topic": "话题名", "content": "帖子内容", "title": "帖子标题", "index": 序号}, ...]
        """
        if not text or len(text.strip()) < 10:
            logger.warning("内容为空或太短，跳过解析")
            return []

        posts = []

        # 第一步：按 ## 话题标题 分组
        topic_sections = self._split_by_topic(text)
        logger.info(f"⚡ 闪电模式：找到 {len(topic_sections)} 个话题分组")

        # 第二步：在每个话题分组内，按 第一篇/第二篇 拆分
        for topic_name, topic_text in topic_sections:
            sub_posts = self._split_by_article(topic_text)

            if sub_posts:
                for i, (title, content) in enumerate(sub_posts, 1):
                    posts.append({
                        "topic": topic_name,
                        "title": title,
                        "content": content.strip(),
                        "index": len(posts) + 1,
                    })
                    logger.debug(f"  话题「{topic_name}」第{i}篇: {title}")
            else:
                # 整个话题只有一篇，没有「第一篇/第二篇」标记
                posts.append({
                    "topic": topic_name,
                    "title": topic_name[:20],  # 用话题名做标题
                    "content": topic_text.strip(),
                    "index": len(posts) + 1,
                })
                logger.debug(f"  话题「{topic_name}」: 单篇")

        logger.success(f"✓ 闪电模式解析完成: {len(posts)} 篇帖子")
        return posts

    def parse_whistleblower(self, text: str) -> List[Dict]:
        """
        解析爆料活动内容

        格式特征：
          1. 标题：xxx
          内容...
          2. 标题：xxx
          内容...
          3. 标题：xxx
          内容...

        返回:
            [{"content": "帖子内容", "title": "帖子标题", "index": 序号}, ...]
        """
        if not text or len(text.strip()) < 10:
            logger.warning("内容为空或太短，跳过解析")
            return []

        posts = []

        # 按编号拆分: "1. " "2. " "3. " 等
        # 支持多种格式: "1. " "1、" "1）" "1) "
        pattern = r'(?:^|\n)\s*(\d+)[\.．、）\)]\s*'

        splits = re.split(pattern, text)

        # splits 的结构: [前缀, 编号1, 内容1, 编号2, 内容2, ...]
        # 过滤掉空前缀
        if splits and not re.match(r'\d+', splits[0].strip()):
            splits = splits[1:]  # 去掉前缀

        # 配对 (编号, 内容)
        i = 0
        while i + 1 < len(splits):
            num = splits[i].strip()
            content = splits[i + 1].strip()
            i += 2

            if not content:
                continue

            # 提取标题（通常在内容的第一行）
            title, body = self._extract_title(content)

            posts.append({
                "content": body.strip(),
                "title": title[:20] if title else "",
                "index": int(num) if num.isdigit() else len(posts) + 1,
            })

        # 如果没有找到编号格式，把整段作为一个帖子
        if not posts and len(text) > 20:
            title, body = self._extract_title(text)
            posts.append({
                "content": body.strip(),
                "title": title[:20] if title else "",
                "index": 1,
            })

        logger.success(f"✓ 爆料模式解析完成: {len(posts)} 篇帖子")
        return posts

    def parse_auto(self, text: str) -> List[Dict]:
        """
        自动判断内容类型并解析

        如果包含 ## 话题标题 或 第一篇/第二篇 → 闪电模式
        如果包含 1. 2. 3. 编号 → 爆料模式
        """
        has_topic_header = bool(re.search(r'^#{1,3}\s+.+', text, re.MULTILINE))
        has_article_marker = bool(re.search(r'[第][一二三四五六七八九十\d]+[篇｜|]', text))
        has_numbering = bool(re.search(r'(?:^|\n)\s*\d+[\.．、）\)]\s*', text))

        if has_topic_header and has_article_marker:
            logger.info("🤖 自动识别: ⚡ 闪电观察者模式")
            return self.parse_lightning(text)
        elif has_numbering:
            logger.info("🤖 自动识别: 🔥 爆料活动模式")
            return self.parse_whistleblower(text)
        elif has_topic_header:
            logger.info("🤖 自动识别: ⚡ 闪电观察者模式（无篇标记）")
            return self.parse_lightning(text)
        else:
            logger.info("🤖 自动识别: 🔥 爆料活动模式（默认）")
            return self.parse_whistleblower(text)

    # ========== 内部方法 ==========

    def _split_by_topic(self, text: str) -> List[tuple]:
        """
        按 ## 话题标题 拆分文本

        返回:
            [("话题名", "话题内容"), ...]
        """
        # 匹配 ## 开头的话题标题
        topic_pattern = r'^#{1,3}\s+(.+)$'

        matches = list(re.finditer(topic_pattern, text, re.MULTILINE))

        if not matches:
            # 没有话题标题，整个文本作为一个话题
            return [("默认话题", text)]

        results = []
        for i, match in enumerate(matches):
            topic_name = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            topic_text = text[start:end].strip()
            results.append((topic_name, topic_text))

        # 如果第一个话题标题之前有内容，也作为一个话题
        if matches[0].start() > 0:
            pre_text = text[:matches[0].start()].strip()
            if pre_text:
                results.insert(0, ("默认话题", pre_text))

        return results

    def _split_by_article(self, text: str) -> List[tuple]:
        """
        按 第X篇 标记拆分文本

        返回:
            [("帖子标题", "帖子内容"), ...]
        """
        # 匹配 **第一篇｜** 或 **第二篇｜** 或 **第三篇｜** 等格式
        # 也匹配 **第一篇|** （半角竖线）
        article_pattern = r'\*{1,2}\s*第[一二三四五六七八九十\d]+[篇]\s*[｜|]\s*(.+?)\s*\*{1,2}'

        matches = list(re.finditer(article_pattern, text))

        if not matches:
            # 尝试更宽松的匹配
            article_pattern2 = r'第[一二三四五六七八九十\d]+[篇]\s*[｜|:：]\s*(.+)'
            matches = list(re.finditer(article_pattern2, text))

        if not matches:
            return []

        results = []
        for i, match in enumerate(matches):
            title = match.group(1).strip().rstrip('*')
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            results.append((title, content))

        # 如果第一个标记之前有内容，作为额外一篇
        if matches[0].start() > 0:
            pre_text = text[:matches[0].start()].strip()
            if len(pre_text) > 20:
                results.insert(0, ("前言", pre_text))

        return results

    def _extract_title(self, content: str) -> tuple:
        """
        从内容中提取标题和正文

        常见格式：
          标题：xxx\n正文...
          **标题**\n正文...

        返回:
            (title, body)
        """
        lines = content.strip().split('\n')

        # 策略1: "标题：" 开头
        for i, line in enumerate(lines[:3]):
            if re.match(r'^标题[：:]', line):
                title = re.sub(r'^标题[：:]\s*', '', line).strip()
                body = '\n'.join(lines[i + 1:]).strip()
                return (title, body)

        # 策略2: **加粗标题** 在第一行
        if lines:
            first = lines[0].strip()
            bold_match = re.match(r'^\*{1,2}(.+?)\*{1,2}$', first)
            if bold_match:
                title = bold_match.group(1).strip()
                body = '\n'.join(lines[1:]).strip()
                return (title, body)

        # 策略3: 第一行较短，可能是标题
        if lines and len(lines[0].strip()) < 30 and len(lines) > 1:
            return (lines[0].strip(), '\n'.join(lines[1:]).strip())

        # 策略4: 没有明确标题
        return ("", content)
