"""
DeepSeek 对话读取器 —— 从 DeepSeek 网页端读取对话历史

功能：
  1. 连接到已启动的 Chrome（CDP 端口 9222）
  2. 打开 DeepSeek 网页端
  3. 定位并打开指定对话
  4. 读取对话中的所有消息（区分用户/AI）
  5. 提取 AI 回复的文字内容
  6. 提取用户消息中的图片

⚠️  前置条件：
  - Chrome 带远程调试端口启动（python3 start_chrome.py）
  - 已登录 chat.deepseek.com
"""

import hashlib
import time
from typing import Optional, List, Dict
from pathlib import Path

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from loguru import logger

from config import settings, PROJECT_ROOT

# Chrome 远程调试地址
CDP_URL = "http://localhost:9222"

# DeepSeek 网址
DEEPSEEK_URL = "https://chat.deepseek.com/"

# 图片下载目录
DOWNLOAD_DIR = PROJECT_ROOT / "downloads" / "deepseek_images"

# 消息角色
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class DeepSeekReader:
    """
    DeepSeek 对话读取器

    用法：
        reader = DeepSeekReader()
        reader.connect()
        reader.open_deepseek()
        reader.open_conversation("职场爆料评论贴创作")
        messages = reader.read_all_messages()
        for msg in messages:
            print(f"[{msg['role']}] {msg['content'][:50]}...")
        reader.disconnect()
    """

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def connect(self) -> bool:
        """连接到 Chrome"""
        logger.info(f"连接到 Chrome（{CDP_URL}）...")
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(CDP_URL)
            self._context = self._browser.contexts[0] if self._browser.contexts else None
            if not self._context:
                logger.error("❌ 未找到浏览器上下文")
                return False
            logger.success("✓ 已连接到 Chrome")
            return True
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        if self._playwright:
            self._playwright.stop()
        logger.info("已断开 Chrome 连接")

    def open_deepseek(self) -> bool:
        """打开或切换到 DeepSeek 页面"""
        logger.info("打开 DeepSeek...")

        for pg in self._context.pages:
            if "chat.deepseek.com" in pg.url:
                self._page = pg
                # 回到首页（对话列表）
                if "/a/chat/" in pg.url:
                    pg.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=10000)
                    time.sleep(2)
                logger.success("✓ DeepSeek 已打开")
                return True

        # 新建页面
        page = self._context.new_page()
        page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(3)
        self._page = page
        logger.success("✓ DeepSeek 已打开")
        return True

    def list_conversations(self, keyword: str = "") -> List[Dict]:
        """
        列出对话列表

        参数:
            keyword: 过滤关键词（可选）

        返回:
            [{"name": "对话名", "href": "链接"}, ...]
        """
        logger.info("获取对话列表...")

        conversations = self._page.evaluate('''() => {
            const results = [];
            const seen = new Set();
            const links = document.querySelectorAll('a');
            for (const a of links) {
                const text = (a.textContent || '').trim();
                const href = a.href || '';
                if (href.includes('/a/chat/s/') && text.length > 0 && text.length < 80) {
                    if (!seen.has(href)) {
                        seen.add(href);
                        results.push({ name: text, href: href });
                    }
                }
            }
            return results;
        }''')

        if keyword:
            conversations = [c for c in conversations if keyword in c['name']]

        logger.info(f"找到 {len(conversations)} 个对话" + (f"（关键词: {keyword}）" if keyword else ""))
        for c in conversations[:10]:
            logger.debug(f"  • {c['name']}")

        return conversations

    def open_conversation(self, name: str) -> bool:
        """
        打开指定名称的对话（支持精确匹配和模糊匹配）

        参数:
            name: 对话名称

        返回:
            True 成功，False 失败
        """
        logger.info(f"打开对话: {name}")

        # 先确保在对话列表页
        if "/a/chat/" in self._page.url:
            self._page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=10000)
            time.sleep(2)

        # 查找匹配的对话
        clicked = self._page.evaluate('''(targetName) => {
            const links = document.querySelectorAll('a');
            // 先精确匹配
            for (const a of links) {
                if (a.textContent.trim() === targetName && a.href.includes('/a/chat/s/')) {
                    a.click();
                    return { found: true, name: a.textContent.trim(), match: 'exact' };
                }
            }
            // 再模糊匹配
            for (const a of links) {
                const text = a.textContent.trim();
                if (text.includes(targetName) && a.href.includes('/a/chat/s/') && text.length < 80) {
                    a.click();
                    return { found: true, name: text, match: 'fuzzy' };
                }
            }
            return { found: false };
        }''', name)

        if not clicked.get('found'):
            logger.error(f"❌ 未找到对话: {name}")
            logger.info("可用对话列表:")
            convs = self.list_conversations()
            for c in convs[:15]:
                logger.info(f"  • {c['name']}")
            return False

        match_type = "精确匹配" if clicked.get('match') == 'exact' else "模糊匹配"
        logger.info(f"  {match_type}: {clicked['name']}")

        # 等待对话加载
        time.sleep(4)

        # 确保对话页面已加载
        retries = 0
        while retries < 3:
            msg_count = self._page.evaluate('''() => {
                return document.querySelectorAll('.ds-message').length;
            }''')
            if msg_count > 0:
                break
            time.sleep(2)
            retries += 1

        logger.success(f"✓ 已打开对话: {clicked['name']}")
        return True

    def read_all_messages(self) -> List[Dict]:
        """
        读取当前对话的所有消息

        返回:
            [{"role": "user"/"assistant", "content": str, "images": [str], "index": int}, ...]
        """
        logger.info("读取对话消息...")

        # 先滚动到底部，确保最新消息可见
        self._scroll_to_bottom()
        time.sleep(1)

        # 逐步滚动读取所有消息
        all_messages = []
        seen_keys = set()

        # 从顶部开始滚动读取
        self._scroll_to_top()
        time.sleep(1)

        max_rounds = 30
        for round_idx in range(max_rounds):
            batch = self._extract_visible_messages()

            new_count = 0
            for msg in batch:
                key = self._message_key(msg)
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_messages.append(msg)
                    new_count += 1

            if round_idx % 5 == 0:
                logger.debug(f"  滚动轮次 {round_idx}: 可见{len(batch)}条, 新增{new_count}条, 累计{len(all_messages)}条")

            # 向下滚动一屏
            can_scroll = self._scroll_down()
            time.sleep(0.3)

            if not can_scroll and new_count == 0:
                logger.debug(f"  已到底部，共读取 {len(all_messages)} 条消息")
                break

        # 按照出现顺序排列，重新分配绝对索引
        # all_messages 是随着滚动逐条追加的，大致按时间顺序
        # 但去重后可能有少量乱序，用 content 哈希排序不可靠，直接保持追加顺序
        # 重新分配绝对索引（0, 1, 2, ...），确保唯一且连续
        for i, msg in enumerate(all_messages):
            msg['index'] = i

        user_count = sum(1 for m in all_messages if m['role'] == ROLE_USER)
        assistant_count = sum(1 for m in all_messages if m['role'] == ROLE_ASSISTANT)
        logger.success(f"✓ 共读取 {len(all_messages)} 条消息 (用户 {user_count}, AI {assistant_count})")

        return all_messages

    def read_new_messages(self, last_index: int = 0) -> List[Dict]:
        """
        读取从 last_index 开始的新消息

        参数:
            last_index: 上次读取的最后一条消息索引

        返回:
            新消息列表
        """
        all_messages = self.read_all_messages()
        new_messages = [m for m in all_messages if m['index'] > last_index]

        logger.info(f"  新消息: {len(new_messages)} 条 (从索引 {last_index} 之后)")
        return new_messages

    def download_image(self, url: str, filename: str = "") -> str:
        """
        下载图片到本地（通过浏览器，复用登录态/Cookie）

        ⚠️ 必须在 connect() 之后、disconnect() 之前调用

        参数:
            url: 图片URL
            filename: 文件名（可选，默认用URL hash）

        返回:
            本地文件路径
        """
        if not filename:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            filename = f"{url_hash}.jpg"

        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        save_path = DOWNLOAD_DIR / filename

        if save_path.exists():
            logger.debug(f"  图片已存在: {filename}")
            return str(save_path)

        try:
            # 方法1：用 Playwright 的 API 请求（自动带 Cookie）
            if self._page and not self._page.is_closed():
                api_request = self._page.context.request
                resp = api_request.get(url)
                if resp.ok:
                    body = resp.body()
                    save_path.write_bytes(body)
                    if save_path.stat().st_size < 1000:
                        save_path.unlink()
                        logger.warning(f"  ⚠️ 图片太小，已删除: {filename}")
                        return ""
                    logger.debug(f"  ✓ 图片下载(浏览器): {filename}")
                    return str(save_path)
        except Exception as e:
            logger.debug(f"  浏览器下载失败，尝试 urllib: {e}")

        try:
            # 方法2：urllib 兜底
            import urllib.request
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                with open(save_path, 'wb') as f:
                    f.write(resp.read())
            if save_path.stat().st_size < 1000:
                save_path.unlink()
                return ""
            logger.debug(f"  ✓ 图片下载(urllib): {filename}")
            return str(save_path)
        except Exception as e:
            logger.warning(f"  ⚠️ 图片下载失败: {url[:60]}... → {e}")
            return ""

    def download_all_images(self, messages: List[Dict]) -> Dict[int, List[str]]:
        """
        批量下载所有消息中的图片（必须在连接期间调用）

        先通过滚动收集所有图片URL（虚拟列表会卸载不可见区域的图片），
        然后逐个下载。

        参数:
            messages: 消息列表（含 images 字段）

        返回:
            {消息index: [本地路径, ...], ...}
        """
        # 先收集所有图片URL（滚动过程中虚拟列表会动态加载/卸载）
        all_image_urls = self._collect_all_image_urls(messages)

        # 下载图片
        result = {}
        for msg_index, urls in all_image_urls.items():
            paths = []
            for url in urls:
                path = self.download_image(url)
                if path:
                    paths.append(path)
            if paths:
                result[msg_index] = paths
                logger.info(f"  消息 [{msg_index}] 下载 {len(paths)} 张图片")
        return result

    def _collect_all_image_urls(self, messages: List[Dict]) -> Dict[int, List[str]]:
        """
        通过滚动整个对话，收集所有用户消息中的图片URL

        虚拟列表只渲染可见区域的消息，图片在不可见时会被卸载。
        所以必须逐步滚动，在每个位置收集可见的图片。

        返回:
            {消息index: [图片URL, ...], ...}
        """
        logger.info("  滚动收集所有图片URL...")

        # 建立消息内容前缀 → index 映射（用于匹配图片所属消息）
        content_to_index = {}
        for msg in messages:
            if msg['role'] == ROLE_USER and msg['content']:
                key = msg['content'][:30]
                content_to_index[key] = msg['index']

        all_images = {}  # {msg_index: set(urls)}

        # 滚动到底部再从顶部开始
        self._scroll_to_bottom()
        time.sleep(1)
        self._scroll_to_top()
        time.sleep(1)

        max_rounds = 50
        for round_idx in range(max_rounds):
            # 提取当前可见的用户消息中的图片
            visible_images = self._page.evaluate('''() => {
                const results = [];
                const msgEls = document.querySelectorAll('.ds-message');

                for (const el of msgEls) {
                    const rect = el.getBoundingClientRect();
                    // 只处理在视口内的消息
                    if (rect.y > window.innerHeight || rect.y + rect.height < 0) continue;

                    const hasAssistantContent = el.querySelector('.ds-assistant-message-main-content') !== null;
                    if (hasAssistantContent) continue;  // 跳过 AI 消息

                    // 提取用户消息文本（前30字）
                    const content = (el.innerText || '').trim().substring(0, 30);

                    // 提取图片 —— 用 naturalWidth 过滤头像/图标
                    const images = [];
                    const imgs = el.querySelectorAll('img');
                    for (const img of imgs) {
                        const src = img.src || '';
                        // 关键：缩略图 naturalWidth 一般 > 100（真实图片），
                        // 头像/图标 naturalWidth < 50
                        if (img.naturalWidth > 80
                            && src.startsWith('http')
                            && !src.includes('avatar')
                            && !src.includes('icon')
                            && (src.includes('deepseeksvc') || src.includes('file_id'))) {
                            images.push(src);
                        }
                    }

                    if (images.length > 0) {
                        results.push({ content, images });
                    }
                }
                return results;
            }''')

            for item in visible_images:
                content_key = item['content']
                msg_index = content_to_index.get(content_key)
                if msg_index is not None:
                    if msg_index not in all_images:
                        all_images[msg_index] = set()
                    for url in item['images']:
                        all_images[msg_index].add(url)

            # 向下滚动
            can_scroll = self._scroll_down()
            time.sleep(0.3)

            if not can_scroll:
                break

        # 转换 set → list
        result = {k: list(v) for k, v in all_images.items()}
        total_imgs = sum(len(v) for v in result.values())
        logger.info(f"  滚动收集完成: {len(result)} 条消息含图片, 共 {total_imgs} 张")

        return result

    # ========== 内部方法 ==========

    def _extract_visible_messages(self) -> List[Dict]:
        """提取当前可见的消息"""
        messages = self._page.evaluate('''() => {
            const msgEls = document.querySelectorAll('.ds-message');
            const results = [];

            for (let i = 0; i < msgEls.length; i++) {
                const el = msgEls[i];

                // 判断角色：有 .ds-assistant-message-main-content 或 .ds-think-content 的是 AI
                const hasAssistantContent = el.querySelector('.ds-assistant-message-main-content') !== null;
                const hasThinkContent = el.querySelector('.ds-think-content') !== null;
                const role = (hasAssistantContent || hasThinkContent) ? 'assistant' : 'user';

                // 提取文本 —— 使用 innerText 保留换行（textContent 会把段落粘在一起）
                let content = '';
                if (role === 'assistant') {
                    const mainContent = el.querySelector('.ds-assistant-message-main-content');
                    if (mainContent) {
                        content = mainContent.innerText.trim();
                    }
                    // 纯思考消息跳过（没有正文内容的）
                } else {
                    content = el.innerText.trim();
                }

                // 提取图片（用 naturalWidth 过滤头像/图标，缩略图展示小但原图大）
                const images = [];
                const imgs = el.querySelectorAll('img');
                for (const img of imgs) {
                    const src = img.src || '';
                    // 缩略图展示64x64但naturalWidth>100，头像naturalWidth<50
                    if (img.naturalWidth > 80
                        && !src.includes('avatar')
                        && !src.includes('icon')
                        && src.startsWith('http')
                        && (src.includes('deepseeksvc') || src.includes('file_id'))) {
                        images.push(src);
                    }
                }

                if (content.length > 0 || images.length > 0) {
                    results.push({
                        role: role,
                        content: content,
                        images: images,
                        index: i,
                        hasThinkContent: hasThinkContent && !hasAssistantContent,
                    });
                }
            }

            return results;
        }''')

        return messages

    def _message_key(self, msg: Dict) -> str:
        """生成消息唯一标识（用于去重）"""
        content_preview = msg['content'][:80] if msg['content'] else ""
        images_key = ",".join(msg.get('images', []))[:50]
        return f"{msg['role']}:{content_preview}:{images_key}"

    def _scroll_to_top(self):
        """滚动到对话顶部"""
        self._page.evaluate('''() => {
            const visible = document.querySelector('.ds-virtual-list-visible-items');
            if (!visible) return;
            // 优先滚动 ds-virtual-list 容器（grandparent），其次是 items 容器（parent）
            const gp = visible.parentElement?.parentElement;
            if (gp && gp.clientHeight < gp.scrollHeight) {
                gp.scrollTop = 0;
            } else {
                visible.parentElement.scrollTop = 0;
            }
        }''')

    def _scroll_to_bottom(self):
        """滚动到对话底部"""
        self._page.evaluate('''() => {
            const visible = document.querySelector('.ds-virtual-list-visible-items');
            if (!visible) return;
            const gp = visible.parentElement?.parentElement;
            if (gp && gp.clientHeight < gp.scrollHeight) {
                gp.scrollTop = gp.scrollHeight;
            } else {
                visible.parentElement.scrollTop = visible.parentElement.scrollHeight;
            }
        }''')

    def _scroll_down(self) -> bool:
        """
        向下滚动一屏

        返回:
            True 还可以继续滚动，False 已到底部
        """
        return self._page.evaluate('''() => {
            const visible = document.querySelector('.ds-virtual-list-visible-items');
            if (!visible) return false;

            // 优先滚动 ds-virtual-list 容器（grandparent）
            const gp = visible.parentElement?.parentElement;
            if (gp && gp.clientHeight < gp.scrollHeight) {
                const before = gp.scrollTop;
                gp.scrollTop += gp.clientHeight * 0.8;
                const after = gp.scrollTop;
                return (after - before) > 10;
            }

            // 备用：滚动 items 容器（parent）
            const container = visible.parentElement;
            const before = container.scrollTop;
            container.scrollTop += container.clientHeight * 0.8;
            const after = container.scrollTop;
            return (after - before) > 10;
        }''')
