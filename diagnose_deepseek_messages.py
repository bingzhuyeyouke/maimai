"""
DeepSeek 消息结构深度探测 —— 理解消息配对和滚动加载机制
"""

import time
from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"


def main():
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    # 找 DeepSeek 页面（应该已经打开了对话）
    ds_page = None
    for pg in context.pages:
        if "chat.deepseek.com" in pg.url:
            ds_page = pg
            break

    if not ds_page:
        print("❌ 未找到 DeepSeek 页面")
        pw.stop()
        return

    print(f"当前页面: {ds_page.url}")

    # 1. 读取所有 ds-message 元素的详细信息
    print("\n" + "=" * 60)
    print("📋 当前可见的 ds-message 元素详情")
    print("=" * 60)

    messages = ds_page.evaluate('''() => {
        const msgEls = document.querySelectorAll('.ds-message');
        const results = [];

        for (const el of msgEls) {
            const cls = (el.className || '').toString();

            // 判断角色
            let role = 'unknown';
            // 用户消息通常有额外的 hash class 且不包含 ds-markdown
            const hasAssistantContent = el.querySelector('.ds-assistant-message-main-content') !== null;
            const hasThinkContent = el.querySelector('.ds-think-content') !== null;
            const hasUserAvatar = el.querySelector('[class*="user-avatar"], [class*="avatar-user"], img[alt*="user"]') !== null;

            if (hasAssistantContent || hasThinkContent) {
                role = 'assistant';
            } else {
                role = 'user';
            }

            // 提取文本
            let text = '';
            if (role === 'assistant') {
                const mainContent = el.querySelector('.ds-assistant-message-main-content');
                if (mainContent) {
                    text = mainContent.textContent.trim();
                } else if (hasThinkContent) {
                    text = '[思考过程]';
                }
            } else {
                text = el.textContent.trim();
            }

            // 提取图片
            const images = [];
            const imgs = el.querySelectorAll('img');
            for (const img of imgs) {
                const rect = img.getBoundingClientRect();
                if (rect.width > 30 && rect.height > 30) {
                    images.push({
                        src: (img.src || '').substring(0, 150),
                        alt: img.alt || '',
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                    });
                }
            }

            results.push({
                role: role,
                className: cls.substring(0, 120),
                textPreview: text.substring(0, 100),
                textLength: text.length,
                imageCount: images.length,
                images: images.slice(0, 3),
                hasAssistantContent: hasAssistantContent,
                hasThinkContent: hasThinkContent,
                childCount: el.children.length,
            });
        }

        return results;
    }''')

    print(f"\n共找到 {len(messages)} 条可见消息:")
    for i, m in enumerate(messages):
        icon = "👤" if m['role'] == 'user' else "🤖"
        print(f"\n  [{i}] {icon} {m['role']}")
        print(f"      class: {m['className']}")
        print(f"      text({m['textLength']}字): {m['textPreview'][:60]}...")
        print(f"      images: {m['imageCount']}, children: {m['childCount']}")
        if m['images']:
            for img in m['images']:
                print(f"        🖼 {img['width']}x{img['height']} src='{img['src'][:60]}'")

    # 2. 测试滚动加载：滚动到顶部，看是否会加载更多消息
    print("\n" + "=" * 60)
    print("📜 测试滚动加载机制")
    print("=" * 60)

    scroll_info = ds_page.evaluate('''() => {
        const container = document.querySelector('.ds-virtual-list-visible-items')?.parentElement;
        if (!container) return { error: '未找到滚动容器' };

        return {
            scrollHeight: container.scrollHeight,
            clientHeight: container.clientHeight,
            scrollTop: container.scrollTop,
            canScrollUp: container.scrollTop > 0,
        };
    }''')
    print(f"  滚动容器: {scroll_info}")

    # 滚动到顶部并检查消息数量变化
    count_before = len(messages)
    ds_page.evaluate('''() => {
        const container = document.querySelector('.ds-virtual-list-visible-items')?.parentElement;
        if (container) {
            container.scrollTop = 0;
        }
    }''')
    time.sleep(2)

    count_after = ds_page.evaluate('''() => {
        return document.querySelectorAll('.ds-message').length;
    }''')

    print(f"  滚动前消息数: {count_before}, 滚动到顶部后: {count_after}")

    # 3. 滚动到底部，获取最新消息
    ds_page.evaluate('''() => {
        const container = document.querySelector('.ds-virtual-list-visible-items')?.parentElement;
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }''')
    time.sleep(2)

    bottom_messages = ds_page.evaluate('''() => {
        const msgEls = document.querySelectorAll('.ds-message');
        const results = [];
        // 取最后5条
        const start = Math.max(0, msgEls.length - 5);
        for (let i = start; i < msgEls.length; i++) {
            const el = msgEls[i];
            const hasAssistantContent = el.querySelector('.ds-assistant-message-main-content') !== null;
            const hasThinkContent = el.querySelector('.ds-think-content') !== null;
            const role = (hasAssistantContent || hasThinkContent) ? 'assistant' : 'user';

            let text = '';
            if (role === 'assistant') {
                const mainContent = el.querySelector('.ds-assistant-message-main-content');
                if (mainContent) text = mainContent.textContent.trim().substring(0, 150);
            } else {
                text = el.textContent.trim().substring(0, 150);
            }

            const images = [];
            const imgs = el.querySelectorAll('img');
            for (const img of imgs) {
                const rect = img.getBoundingClientRect();
                if (rect.width > 30 && rect.height > 30) {
                    images.push(img.src?.substring(0, 100) || '');
                }
            }

            results.push({
                index: i,
                role: role,
                textPreview: text,
                imageCount: images.length,
                images: images,
            });
        }
        return results;
    }''')

    print(f"\n  滚动到底部后，最后5条消息:")
    for m in bottom_messages:
        icon = "👤" if m['role'] == 'user' else "🤖"
        print(f"    [{m['index']}] {icon} text='{m['textPreview'][:80]}...' images={m['imageCount']}")

    # 4. 探测完整消息计数方法
    total_count = ds_page.evaluate('''() => {
        // 尝试找到总消息数的标识
        // 方法1: 查看 aria 属性
        const ariaLive = document.querySelector('[aria-live="polite"]');
        // 方法2: 查看虚拟列表的总高度推断
        const container = document.querySelector('.ds-virtual-list-visible-items')?.parentElement;
        const listItems = document.querySelector('.ds-virtual-list-visible-items');

        return {
            ariaLiveText: ariaLive?.textContent || 'none',
            containerScrollHeight: container?.scrollHeight || 0,
            containerClientHeight: container?.clientHeight || 0,
            listItemsChildCount: listItems?.children.length || 0,
            visibleMsgCount: document.querySelectorAll('.ds-message').length,
        };
    }''')
    print(f"\n📊 消息计数信息: {total_count}")

    # 5. 生成完整滚动读取策略的测试
    print("\n" + "=" * 60)
    print("🔄 测试逐步滚动读取所有消息")
    print("=" * 60)

    all_messages = []
    seen_texts = set()

    # 先滚动到顶部
    ds_page.evaluate('''() => {
        const container = document.querySelector('.ds-virtual-list-visible-items')?.parentElement;
        if (container) container.scrollTop = 0;
    }''')
    time.sleep(2)

    # 逐步向下滚动
    for scroll_round in range(20):  # 最多20轮
        batch = ds_page.evaluate('''() => {
            const msgEls = document.querySelectorAll('.ds-message');
            const results = [];
            for (const el of msgEls) {
                const hasAssistantContent = el.querySelector('.ds-assistant-message-main-content') !== null;
                const hasThinkContent = el.querySelector('.ds-think-content') !== null;
                const role = (hasAssistantContent || hasThinkContent) ? 'assistant' : 'user';

                let text = '';
                if (role === 'assistant') {
                    const mainContent = el.querySelector('.ds-assistant-message-main-content');
                    if (mainContent) text = mainContent.textContent.trim();
                } else {
                    text = el.textContent.trim();
                }

                const textKey = text.substring(0, 80);
                if (textKey && !results.some(r => r.textKey === textKey)) {
                    results.push({
                        role: role,
                        textKey: textKey,
                        textLength: text.length,
                    });
                }
            }
            return results;
        }''')

        new_count = 0
        for m in batch:
            if m['textKey'] not in seen_texts:
                seen_texts.add(m['textKey'])
                all_messages.append(m)
                new_count += 1

        if scroll_round % 5 == 0 or new_count > 0:
            print(f"  滚动轮次 {scroll_round}: 可见{len(batch)}条, 新增{new_count}条, 累计{len(all_messages)}条")

        if new_count == 0 and scroll_round > 0:
            # 没有新消息了，可能到底了
            # 但先确认是否真的到底
            at_bottom = ds_page.evaluate('''() => {
                const container = document.querySelector('.ds-virtual-list-visible-items')?.parentElement;
                if (!container) return true;
                return container.scrollTop + container.clientHeight >= container.scrollHeight - 50;
            }''')
            if at_bottom:
                print(f"  ✅ 已滚动到底部，共读取 {len(all_messages)} 条消息")
                break

        # 向下滚动一屏
        ds_page.evaluate('''() => {
            const container = document.querySelector('.ds-virtual-list-visible-items')?.parentElement;
            if (container) {
                container.scrollTop += container.clientHeight * 0.8;
            }
        }''')
        time.sleep(0.5)

    # 统计
    user_count = sum(1 for m in all_messages if m['role'] == 'user')
    assistant_count = sum(1 for m in all_messages if m['role'] == 'assistant')
    print(f"\n📈 最终统计: 共 {len(all_messages)} 条 (用户 {user_count} + AI {assistant_count})")

    pw.stop()
    print("\n✅ 探测完成")


if __name__ == "__main__":
    main()
