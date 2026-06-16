"""
网络搜图模块 —— 为帖子自动搜索配图

当前实现：Bing Image Search（无需API Key，通过浏览器自动化搜索并提取图片URL）

用法：
    searcher = ImageSearcher()
    searcher.connect()
    paths = searcher.search_and_download("巴西队足球", count=3)
    searcher.disconnect()
"""

import hashlib
import re
import time
from typing import Optional, List
from pathlib import Path

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from loguru import logger

from config import settings, PROJECT_ROOT

# Chrome 远程调试地址
CDP_URL = "http://localhost:9222"

# 图片下载目录
DOWNLOAD_DIR = PROJECT_ROOT / "downloads" / "search_images"

# Bing 图片搜索 URL
BING_IMAGE_URL = "https://www.bing.com/images/search"


class ImageSearcher:
    """
    网络搜图器（Bing Image Search）

    用法：
        searcher = ImageSearcher()
        searcher.connect()
        paths = searcher.search_and_download("巴西队足球", count=3)
        searcher.disconnect()
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

    def search_images(self, query: str, count: int = 3) -> List[str]:
        """
        搜索图片，返回图片URL列表

        参数:
            query: 搜索关键词
            count: 需要的图片数量

        返回:
            图片URL列表
        """
        logger.info(f"🔍 搜索图片: '{query}' (需要{count}张)")

        # 新建标签页搜索
        page = self._context.new_page()
        try:
            search_url = f"{BING_IMAGE_URL}?q={query}&first=1"
            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)

            # 提取图片URL
            image_urls = page.evaluate('''(count) => {
                const results = [];
                // Bing 图片搜索结果中的图片元素
                const imgs = document.querySelectorAll('img.mimg, img[src*="th?id="]');
                for (let i = 0; i < Math.min(imgs.length, count * 3); i++) {
                    const img = imgs[i];
                    const src = img.src || '';

                    // 优先取缩略图的高质量版本
                    if (src.includes('th?id=')) {
                        // 构建高质量URL
                        const baseUrl = src.split('&')[0];
                        results.push(baseUrl + '&w=800&h=600&c=7');
                    } else if (src.startsWith('http') && !src.includes('favicon') && !src.includes('logo')) {
                        results.push(src);
                    }
                }

                // 备用：从 data 属性获取原图URL
                const anchors = document.querySelectorAll('a.iusc');
                for (let i = 0; i < anchors.length && results.length < count; i++) {
                    const m = anchors[i].getAttribute('m');
                    if (m) {
                        try {
                            const data = JSON.parse(m);
                            if (data.murl) results.push(data.murl);
                        } catch(e) {}
                    }
                }

                return [...new Set(results)].slice(0, count * 2);
            }''', count)

            logger.info(f"  找到 {len(image_urls)} 个图片URL")
            return image_urls

        except Exception as e:
            logger.error(f"❌ 搜索失败: {e}")
            return []
        finally:
            page.close()

    def download_image(self, url: str, filename: str = "") -> str:
        """
        下载图片到本地

        参数:
            url: 图片URL
            filename: 文件名（可选）

        返回:
            本地文件路径
        """
        if not filename:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            # 从URL推断扩展名
            ext = ".jpg"
            if "png" in url.lower():
                ext = ".png"
            elif "webp" in url.lower():
                ext = ".webp"
            filename = f"{url_hash}{ext}"

        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        save_path = DOWNLOAD_DIR / filename

        if save_path.exists():
            logger.debug(f"  图片已存在: {filename}")
            return str(save_path)

        try:
            import urllib.request
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                with open(save_path, 'wb') as f:
                    f.write(resp.read())

            # 检查文件大小（太小的可能是错误响应）
            if save_path.stat().st_size < 5000:
                save_path.unlink()
                logger.warning(f"  ⚠️ 图片太小，已删除: {filename}")
                return ""

            logger.debug(f"  ✓ 图片下载: {filename}")
            return str(save_path)
        except Exception as e:
            logger.warning(f"  ⚠️ 图片下载失败: {url[:60]}... → {e}")
            return ""

    def search_and_download(self, query: str, count: int = 3) -> List[str]:
        """
        搜索图片并下载到本地

        参数:
            query: 搜索关键词
            count: 需要的图片数量

        返回:
            本地图片路径列表
        """
        urls = self.search_images(query, count)
        if not urls:
            logger.warning(f"  未找到图片: {query}")
            return []

        local_paths = []
        for url in urls:
            path = self.download_image(url)
            if path:
                local_paths.append(path)
            if len(local_paths) >= count:
                break

        logger.success(f"✓ 搜图完成: '{query}' → {len(local_paths)} 张")
        return local_paths
