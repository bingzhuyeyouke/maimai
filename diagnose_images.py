"""快速探测包含图片的 DeepSeek 对话"""

import time
from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
DEEPSEEK_URL = "https://chat.deepseek.com/"


def main():
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    # 找 DeepSeek 页面
    ds_page = None
    for pg in context.pages:
        if "chat.deepseek.com" in pg.url:
            ds_page = pg
            break

    # 先回到对话列表
    if ds_page:
        ds_page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2)

    # 列出对话
    conversations = ds_page.evaluate('''() => {
        const results = [];
        const seen = new Set();
        const links = document.querySelectorAll('a');
        for (const a of links) {
            const text = (a.textContent || '').trim();
            const href = a.href || '';
            if (href.includes('/a/chat/s/') && text.length > 0 && text.length < 80 && !seen.has(href)) {
                seen.add(href);
                results.push({ name: text, href: href });
            }
        }
        return results;
    }''')

    print(f"找到 {len(conversations)} 个对话")

    # 找包含"爆料"关键词的对话
    target_convs = [c for c in conversations if '爆料' in c['name'] or '闪电' in c['name'] or '观察' in c['name']]
    if not target_convs:
        target_convs = conversations[:3]  # fallback

    print(f"目标对话: {[c['name'] for c in target_convs]}")

    for conv in target_convs[:2]:
        print(f"\n{'='*60}")
        print(f"📖 打开对话: {conv['name']}")
        print(f"{'='*60}")

        # 点击对话
        ds_page.evaluate('''(targetHref) => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                if (a.href === targetHref) { a.click(); return true; }
            }
            return false;
        }''', conv['href'])
        time.sleep(4)

        # 读取消息
        messages = ds_page.evaluate('''() => {
            const msgEls = document.querySelectorAll('.ds-message');
            const results = [];

            for (let i = 0; i < msgEls.length; i++) {
                const el = msgEls[i];
                const hasAssistantContent = el.querySelector('.ds-assistant-message-main-content') !== null;
                const hasThinkContent = el.querySelector('.ds-think-content') !== null;
                const role = (hasAssistantContent || hasThinkContent) ? 'assistant' : 'user';

                // 提取文本
                let text = '';
                if (role === 'assistant') {
                    const mainContent = el.querySelector('.ds-assistant-message-main-content');
                    if (mainContent) text = mainContent.textContent.trim();
                } else {
                    text = el.textContent.trim();
                }

                // 提取所有 img 标签（包括小图）
                const allImgs = [];
                const imgs = el.querySelectorAll('img');
                for (const img of imgs) {
                    const rect = img.getBoundingClientRect();
                    allImgs.push({
                        src: (img.src || '').substring(0, 200),
                        alt: (img.alt || '').substring(0, 50),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        parentClass: (img.parentElement?.className || '').toString().substring(0, 80),
                        grandparentClass: (img.parentElement?.parentElement?.className || '').toString().substring(0, 80),
                    });
                }

                // 查找图片容器（可能是 div 包裹图片）
                const imgContainers = el.querySelectorAll('[class*="image"], [class*="img"], [class*="upload"], [class*="attachment"]');
                const containerInfo = [];
                for (const c of imgContainers) {
                    containerInfo.push({
                        className: (c.className || '').toString().substring(0, 100),
                        tag: c.tagName,
                        innerImgSrc: c.querySelector('img')?.src?.substring(0, 150) || '',
                    });
                }

                results.push({
                    index: i,
                    role: role,
                    textPreview: text.substring(0, 120),
                    textLength: text.length,
                    allImages: allImgs,
                    imgContainers: containerInfo,
                });
            }

            return results;
        }''')

        print(f"  消息数: {len(messages)}")
        for m in messages:
            icon = "👤" if m['role'] == 'user' else "🤖"
            img_info = ""
            if m['allImages']:
                img_info = f" 🖼️({len(m['allImages'])}imgs)"
            print(f"  [{m['index']}] {icon} ({m['textLength']}字){img_info}: {m['textPreview'][:60]}...")
            if m['allImages']:
                for img in m['allImages']:
                    print(f"      img: {img['width']}x{img['height']} parent='{img['parentClass'][:40]}' src='{img['src'][:50]}'")
            if m['imgContainers']:
                for c in m['imgContainers']:
                    print(f"      container: <{c['tag']}> class='{c['className'][:50]}'")

        # 回到对话列表
        ds_page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2)

    pw.stop()
    print("\n✅ 探测完成")


if __name__ == "__main__":
    main()
