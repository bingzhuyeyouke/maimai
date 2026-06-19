"""
图片搜索模块 — 根据话题名称搜索相关配图

支持两种搜图方式：
  1. 网页搜图（默认）：通过 Playwright 打开百度图片搜索，零配置
  2. Pexels API：高质量图库，需要配置 PEXELS_API_KEY

用法：
    from adapter.image_search import search_and_download

    img_path = search_and_download("AI大模型", "/path/to/save")
    # img_path = "/path/to/save/AI大模型.jpg" 或 None

前置条件（网页搜图模式）：
    Chrome 带调试端口启动（python3 start_chrome.py），已登录百度
"""

import re
import time
from pathlib import Path
from typing import Optional, List

import requests
from loguru import logger
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

from config import settings, PROJECT_ROOT


# ========== 网页搜图（百度图片）==========

CDP_URL = "http://localhost:9222"
BAIDU_IMAGE_URL = "https://image.baidu.com/search/index"


def search_image_web(query: str) -> Optional[str]:
    """
    通过百度图片网页搜索，返回第一张大图 URL

    参数:
        query: 搜索关键词

    返回:
        图片 URL 或 None
    """
    try:
        p = sync_playwright().start()
        browser = p.chromium.connect_over_cdp(CDP_URL, timeout=15000)
        context = browser.contexts[0]
        page = context.new_page()

        try:
            # 搜索百度图片
            url = f"{BAIDU_IMAGE_URL}?tn=baiduimage&word={query}"
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)

            # 提取搜索结果中的图片 URL
            img_urls = page.evaluate('''() => {
                const results = [];
                // 百度图片搜索结果中的 img 标签
                const imgs = document.querySelectorAll('img.main_img, img[data-imgurl], .imgitem img, .imgbox img');
                for (const img of imgs) {
                    const src = img.dataset.imgurl || img.src || '';
                    if (src && (src.startsWith('http') || src.startsWith('https'))) {
                        const rect = img.getBoundingClientRect();
                        // 过滤小图和图标
                        if (rect.width > 100 && rect.height > 80) {
                            results.push(src);
                        }
                    }
                }
                // 备用：从所有 img 中找
                if (results.length === 0) {
                    const allImgs = document.querySelectorAll('img');
                    for (const img of allImgs) {
                        const src = img.src || img.dataset.imgurl || '';
                        const rect = img.getBoundingClientRect();
                        if (src.startsWith('http') && rect.width > 150 && rect.height > 100) {
                            results.push(src);
                        }
                    }
                }
                return results.slice(0, 5);
            }''')

            if img_urls:
                # 优先选大图（不含 thumb/baidu 相关的缩略图 URL）
                for url in img_urls:
                    if 'thumb' not in url.lower() and 'baidu' not in url.split('/')[-1].lower():
                        logger.info(f"  📷 网页搜图: {query} → 找到图片")
                        return url
                # 没有大图就用第一张
                logger.info(f"  📷 网页搜图: {query} → 找到图片（缩略图）")
                return img_urls[0]

            logger.warning(f"  ⚠️ 网页搜图未找到: {query}")
            return None

        finally:
            page.close()
            p.stop()

    except Exception as e:
        logger.warning(f"  ⚠️ 网页搜图异常: {e}")
        return None


# ========== Pexels API 搜图（备用）==========

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def search_image_pexels(query: str, orientation: str = "landscape") -> Optional[str]:
    """
    通过 Pexels API 搜索图片

    参数:
        query: 搜索关键词

    返回:
        图片 URL 或 None
    """
    api_key = settings.pexels_api_key
    if not api_key:
        return None

    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "per_page": 3,
        "orientation": orientation,
        "size": "medium",
        "locale": "zh-CN",
    }

    try:
        resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            return None

        photos = resp.json().get("photos", [])
        if not photos:
            return None

        return photos[0]["src"]["large"]

    except Exception:
        return None


# ========== 通用下载 ==========

def download_image(url: str, save_path: str) -> Optional[str]:
    """
    下载图片到本地

    参数:
        url: 图片 URL
        save_path: 本地保存路径

    返回:
        保存路径或 None
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": url,
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200 or len(resp.content) < 5000:
            # 小于5KB可能是错误页
            return None

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_bytes(resp.content)
        return save_path

    except Exception as e:
        logger.warning(f"  ⚠️ 图片下载异常: {e}")
        return None


# ========== 组合方法 ==========

def search_and_download(query: str, save_dir: str, skip_web: bool = False, pexels_query: str = None) -> Optional[str]:
    """
    搜索并下载一张图片（优先网页搜图，Pexels作备用）

    参数:
        query: 搜索关键词（话题名称）
        save_dir: 保存目录
        skip_web: 跳过网页搜图（避免Playwright事件循环冲突）
        pexels_query: Pexels专用搜索词（英文），不传则用query

    返回:
        本地文件路径或 None
    """
    # 文件名：话题名安全化 + .jpg
    safe_name = re.sub(r'[^\w一-鿿]', '_', query)[:30] + '.jpg'
    save_path = str(Path(save_dir) / safe_name)

    # 方式1：网页搜图（百度图片）— 可跳过避免Playwright冲突
    img_url = None
    if not skip_web:
        img_url = search_image_web(query)

    # 方式2：Pexels API 备用（或主用）
    if not img_url:
        pexels_q = pexels_query or query
        img_url = search_image_pexels(pexels_q)

    if not img_url:
        logger.warning(f"  ⚠️ 未找到图片: {query}")
        return None

    downloaded = download_image(img_url, save_path)
    if downloaded:
        logger.success(f"  ✓ 图片下载: {query} → {safe_name}")
    return downloaded
