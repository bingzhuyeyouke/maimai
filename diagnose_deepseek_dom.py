"""
DeepSeek DOM 诊断脚本 —— 探测对话页面结构，为 deepseek_reader.py 提供选择器依据

用法：
  python3 diagnose_deepseek_dom.py
"""

import json
import time
from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
DEEPSEEK_URL = "https://chat.deepseek.com/"


def main():
    print("=" * 60)
    print("DeepSeek DOM 诊断")
    print("=" * 60)

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    # 找 DeepSeek 页面
    ds_page = None
    for pg in context.pages:
        if "chat.deepseek.com" in pg.url:
            ds_page = pg
            break

    if not ds_page:
        print("❌ 未找到 DeepSeek 页面，正在打开...")
        ds_page = context.new_page()
        ds_page.goto(DEEPSEEK_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(3)

    current_url = ds_page.url
    print(f"当前页面: {current_url}")

    # 如果在对话列表页，检查对话列表
    if "/a/chat/s/" not in current_url:
        print("\n📋 当前在对话列表页，探测对话列表结构...")
        conversations = ds_page.evaluate('''() => {
            const results = [];
            const links = document.querySelectorAll('a');
            for (const a of links) {
                const text = (a.textContent || '').trim();
                const href = a.href || '';
                if (href.includes('/a/chat/s/') && text.length > 0 && text.length < 50) {
                    results.push({ name: text, href: href });
                }
            }
            return results;
        }''')
        print(f"  找到 {len(conversations)} 个对话:")
        for i, c in enumerate(conversations[:10]):
            print(f"    {i+1}. {c['name']}")

        if conversations:
            # 打开第一个对话来探测消息结构
            print(f"\n📖 打开第一个对话来探测消息结构...")
            target_href = conversations[0]['href']
            ds_page.evaluate('''(targetHref) => {
                const links = document.querySelectorAll('a');
                for (const a of links) {
                    if (a.href === targetHref) { a.click(); return; }
                }
            }''', target_href)
            time.sleep(5)

    # 探测消息区域结构
    print("\n" + "=" * 60)
    print("🔍 探测消息区域 DOM 结构")
    print("=" * 60)

    # 1. 探测整体聊天容器
    container_info = ds_page.evaluate('''() => {
        const candidates = [
            'main', '[class*="chat"]', '[class*="conversation"]',
            '[class*="message-list"]', '[class*="dialog"]',
            '[role="log"]', '[class*="content-area"]',
        ];
        const results = [];
        for (const sel of candidates) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                const rect = el.getBoundingClientRect();
                if (rect.height > 200) {  // 大容器
                    results.push({
                        selector: sel,
                        tag: el.tagName,
                        className: el.className.substring(0, 100),
                        childCount: el.children.length,
                        height: Math.round(rect.height),
                    });
                }
            }
        }
        return results;
    }''')
    print("\n📦 可能的聊天容器:")
    for c in container_info:
        print(f"  {c['selector']} → <{c['tag']}> class='{c['className']}' children={c['childCount']} height={c['height']}")

    # 2. 探测消息元素结构
    message_info = ds_page.evaluate('''() => {
        const results = {
            by_data_role: [],
            by_class_msg: [],
            by_ds_prefix: [],
            all_direct_children: [],
        };

        // Strategy A: data-role 属性
        document.querySelectorAll('[data-role]').forEach(el => {
            results.by_data_role.push({
                role: el.getAttribute('data-role'),
                tag: el.tagName,
                className: (el.className || '').substring(0, 80),
                textPreview: el.textContent.substring(0, 50).trim(),
            });
        });

        // Strategy B: class 包含 message/msg/chat
        document.querySelectorAll('[class*="message"], [class*="msg-"], [class*="chat-message"]').forEach(el => {
            results.by_class_msg.push({
                tag: el.tagName,
                className: (el.className || '').substring(0, 80),
                textPreview: el.textContent.substring(0, 50).trim(),
            });
        });

        // Strategy C: ds- 前缀的容器（DeepSeek 自定义组件）
        document.querySelectorAll('[class*="ds-"]').forEach(el => {
            const cls = (el.className || '').toString();
            if (cls.includes('message') || cls.includes('msg') || cls.includes('chat') || cls.includes('bubble')) {
                results.by_ds_prefix.push({
                    tag: el.tagName,
                    className: cls.substring(0, 100),
                    textPreview: el.textContent.substring(0, 50).trim(),
                });
            }
        });

        // Strategy D: 找 markdown 块（AI 回复的标志）的父级结构
        const markdownBlocks = document.querySelectorAll('[class*="ds-markdown"], [class*="markdown"]');
        if (markdownBlocks.length > 0) {
            const firstBlock = markdownBlocks[0];
            // 向上3层
            let parent = firstBlock;
            const ancestry = [];
            for (let i = 0; i < 5 && parent.parentElement; i++) {
                parent = parent.parentElement;
                ancestry.push({
                    tag: parent.tagName,
                    className: (parent.className || '').toString().substring(0, 100),
                    childCount: parent.children.length,
                });
            }
            results.markdown_ancestry = ancestry;
            results.markdown_count = markdownBlocks.length;
        }

        return results;
    }''')

    print(f"\n🏷️  data-role 消息元素: {len(message_info['by_data_role'])} 个")
    for m in message_info['by_data_role'][:5]:
        print(f"  data-role='{m['role']}' <{m['tag']}> class='{m['className']}' → '{m['textPreview'][:30]}...'")

    print(f"\n💬 class*='message/msg' 元素: {len(message_info['by_class_msg'])} 个")
    for m in message_info['by_class_msg'][:5]:
        print(f"  <{m['tag']}> class='{m['className']}' → '{m['textPreview'][:30]}...'")

    print(f"\n🔧 ds-* 前缀消息相关元素: {len(message_info['by_ds_prefix'])} 个")
    for m in message_info['by_ds_prefix'][:5]:
        print(f"  <{m['tag']}> class='{m['className']}' → '{m['textPreview'][:30]}...'")

    if 'markdown_ancestry' in message_info:
        print(f"\n📝 Markdown 块数量: {message_info['markdown_count']}")
        print("  Markdown 祖先链:")
        for a in message_info['markdown_ancestry']:
            print(f"    <{a['tag']}> class='{a['className']}' children={a['childCount']}")

    # 3. 探测用户消息 vs AI 消息的区分方式
    print("\n" + "=" * 60)
    print("🔬 深入探测消息配对结构")
    print("=" * 60)

    pair_info = ds_page.evaluate('''() => {
        // 找所有 ds-markdown--block（AI回复的标志）
        const aiBlocks = document.querySelectorAll('[class*="ds-markdown--block"]');
        const results = [];

        for (let i = Math.max(0, aiBlocks.length - 3); i < aiBlocks.length; i++) {
            const block = aiBlocks[i];
            // 找它的最近的消息容器（向上找3-5层）
            let container = block;
            for (let j = 0; j < 6; j++) {
                if (container.parentElement) container = container.parentElement;
                const cls = (container.className || '').toString();
                // 如果找到带 message/chat 相关类的容器就停
                if (cls.includes('message') || cls.includes('msg') || cls.includes('chat') ||
                    cls.includes('bubble') || cls.includes('group')) {
                    break;
                }
            }

            // 现在找到这个 AI 消息的容器，看看它的前一个兄弟（可能是用户消息）
            const prev = container.previousElementSibling;
            const next = container.nextElementSibling;

            results.push({
                aiContainer: {
                    tag: container.tagName,
                    className: (container.className || '').toString().substring(0, 100),
                    textPreview: container.textContent.substring(0, 80).trim(),
                },
                prevSibling: prev ? {
                    tag: prev.tagName,
                    className: (prev.className || '').toString().substring(0, 100),
                    textPreview: prev.textContent.substring(0, 80).trim(),
                } : null,
                nextSibling: next ? {
                    tag: next.tagName,
                    className: (next.className || '').toString().substring(0, 100),
                    textPreview: next.textContent.substring(0, 80).trim(),
                } : null,
            });
        }

        return results;
    }''')

    for i, p in enumerate(pair_info):
        print(f"\n  消息对 {i+1}:")
        print(f"    AI容器: <{p['aiContainer']['tag']}> class='{p['aiContainer']['className']}'")
        print(f"      → '{p['aiContainer']['textPreview'][:40]}...'")
        if p['prevSibling']:
            print(f"    前一个兄弟: <{p['prevSibling']['tag']}> class='{p['prevSibling']['className']}'")
            print(f"      → '{p['prevSibling']['textPreview'][:40]}...'")
        if p['nextSibling']:
            print(f"    后一个兄弟: <{p['nextSibling']['tag']}> class='{p['nextSibling']['className']}'")

    # 4. 探测图片元素
    print("\n" + "=" * 60)
    print("🖼️  探测消息中的图片")
    print("=" * 60)

    image_info = ds_page.evaluate('''() => {
        const imgs = document.querySelectorAll('img');
        const results = [];
        for (const img of imgs) {
            const src = img.src || '';
            const alt = img.alt || '';
            const cls = (img.className || '').toString();
            const rect = img.getBoundingClientRect();
            // 过滤小图标和头像
            if (rect.width > 50 && rect.height > 50 && !src.includes('avatar') && !src.includes('icon')) {
                results.push({
                    src: src.substring(0, 120),
                    alt: alt.substring(0, 50),
                    className: cls.substring(0, 80),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    parentClassName: (img.parentElement?.className || '').toString().substring(0, 80),
                });
            }
        }
        return results;
    }''')

    print(f"  找到 {len(image_info)} 张大图:")
    for img in image_info[:5]:
        print(f"    {img['width']}x{img['height']} src='{img['src'][:60]}...' parent='{img['parentClassName']}'")

    # 5. 导出完整的消息区域 HTML 结构（前几层）
    print("\n" + "=" * 60)
    print("📄 消息区域 HTML 结构摘要（最后3条消息）")
    print("=" * 60)

    html_summary = ds_page.evaluate('''() => {
        // 找所有 markdown 块，取最后3个所在的容器
        const aiBlocks = document.querySelectorAll('[class*="ds-markdown--block"]');
        if (aiBlocks.length === 0) return "No markdown blocks found";

        const results = [];
        const start = Math.max(0, aiBlocks.length - 3);

        for (let i = start; i < aiBlocks.length; i++) {
            const block = aiBlocks[i];
            // 向上找消息容器
            let el = block;
            for (let j = 0; j < 8 && el.parentElement; j++) {
                el = el.parentElement;
            }
            // 生成精简 HTML
            const html = el.innerHTML.substring(0, 500);
            results.push({
                index: i,
                outerTag: `<${el.tagName} class="${(el.className||'').toString().substring(0,80)}">`,
                htmlPreview: html,
            });
        }
        return results;
    }''')

    if isinstance(html_summary, list):
        for item in html_summary:
            print(f"\n  [{item['index']}] {item['outerTag']}")
            print(f"    {item['htmlPreview'][:200]}...")
    else:
        print(f"  {html_summary}")

    pw.stop()
    print("\n✅ 诊断完成")


if __name__ == "__main__":
    main()
