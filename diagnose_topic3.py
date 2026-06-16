"""探测工具栏的完整结构和添加话题弹出面板"""

import time
from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
MAIMAI_URL = "https://maimai.cn/community/home/recommended"


def main():
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    page = None
    for pg in context.pages:
        if "maimai.cn" in pg.url and not pg.is_closed():
            page = pg
            break

    if not page:
        page = context.new_page()
        page.goto(MAIMAI_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(5)
    else:
        page.goto(MAIMAI_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(3)

    # 1. 探测工具栏的完整结构
    print("=" * 60)
    print("🔧 工具栏结构（编辑器下方的按钮区域）")
    print("=" * 60)

    toolbar = page.evaluate('''() => {
        const results = [];

        // 找到包含 picture 和 video file input 的容器
        const pictureInput = document.getElementById('picture');
        if (!pictureInput) return [{ error: '未找到 #picture input' }];

        // 找工具栏容器（file input 的祖先）
        let toolbarEl = pictureInput.parentElement;
        for (let i = 0; i < 5 && toolbarEl; i++) {
            const children = toolbarEl.children.length;
            if (children >= 3) break;  // 找到有多个子元素的容器
            toolbarEl = toolbarEl.parentElement;
        }

        if (!toolbarEl) return [{ error: '未找到工具栏容器' }];

        // 遍历工具栏的所有子元素
        for (const child of toolbarEl.children) {
            const rect = child.getBoundingClientRect();
            const text = (child.textContent || '').trim().substring(0, 50);
            const tag = child.tagName;
            const cls = (child.className || '').substring(0, 60);
            const id = child.id || '';

            // 检查是否有 file input
            const fileInput = child.querySelector('input[type="file"]');
            const fileInputId = fileInput ? fileInput.id : '';

            // 检查是否有 svg 图标
            const hasSvg = child.querySelector('svg') !== null;

            results.push({
                tag, text, id, cls,
                position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                fileInputId,
                hasSvg,
            });
        }

        return results;
    }''')

    for item in toolbar:
        extras = []
        if item.get('fileInputId'):
            extras.append(f"fileInput={item['fileInputId']}")
        if item.get('hasSvg'):
            extras.append("hasSvg")
        print(f"  <{item['tag']}> text='{item['text'][:30]}' id='{item.get('id', '')}' at {item.get('position', '?')} {' '.join(extras)}")

    # 2. 点击 # 添加话题 并详细观察弹出面板
    print("\n" + "=" * 60)
    print("🔍 点击 '# 添加话题' 后的弹出面板")
    print("=" * 60)

    # 先关闭可能存在的弹出面板
    page.keyboard.press('Escape')
    time.sleep(1)

    # 找到并点击 # 添加话题
    # 它可能是一个带 # 号的按钮/标签
    topic_btn_info = page.evaluate('''() => {
        const results = [];
        const all = document.querySelectorAll('span, div, button, label');
        for (const el of all) {
            const t = (el.textContent || '').trim();
            const rect = el.getBoundingClientRect();
            // 在工具栏区域 (y > 250)
            if ((t.includes('添加话题') || t.includes('#') || t.includes('话题')) && rect.y > 250 && rect.width > 0) {
                results.push({
                    text: t.substring(0, 50),
                    tag: el.tagName,
                    position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                    size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                    className: (el.className || '').substring(0, 60),
                    htmlFor: el.getAttribute('for') || '',
                });
            }
        }
        return results;
    }''')

    print(f"工具栏区域包含'话题'的元素:")
    for item in topic_btn_info:
        print(f"  <{item['tag']}> '{item['text']}' at {item['position']} size={item['size']} for='{item.get('htmlFor', '')}' class='{item.get('className', '')}'")

    # 点击文本为 "# 添加话题" 或 "添加话题" 的元素
    click_result = page.evaluate('''() => {
        const all = document.querySelectorAll('span, div, label, button');
        for (const el of all) {
            const t = (el.textContent || '').trim();
            const rect = el.getBoundingClientRect();
            if ((t === '# 添加话题' || t === '添加话题') && rect.y > 250 && rect.width > 0) {
                el.click();
                return { clicked: t, position: `${rect.x},${rect.y}` };
            }
        }
        return { clicked: false };
    }''')
    print(f"\n点击结果: {click_result}")
    time.sleep(2)

    # 截图
    page.screenshot(path="/tmp/maimai_topic_detailed.png")

    # 3. 详细分析弹出面板
    print("\n" + "=" * 60)
    print("📋 弹出面板详细分析")
    print("=" * 60)

    panel_info = page.evaluate('''() => {
        const results = [];

        // 找所有在弹出面板区域的元素
        // 弹出面板通常是一个固定定位或绝对定位的容器
        // 位置在编辑器下方

        // 方法1：找最近出现的容器（z-index 较高）
        const allDivs = document.querySelectorAll('div');
        for (const div of allDivs) {
            const style = window.getComputedStyle(div);
            const zIndex = style.zIndex;
            const position = style.position;
            const rect = div.getBoundingClientRect();

            // 弹出面板特征：z-index 较高 或 position=fixed/absolute
            // 且在页面中间偏下区域
            if (rect.width > 300 && rect.height > 100 && rect.y > 200 && rect.y < 500
                && (zIndex !== 'auto' || position === 'fixed' || position === 'absolute')) {
                results.push({
                    type: 'panel',
                    tag: div.tagName,
                    position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                    size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                    zIndex,
                    cssPosition: position,
                    className: (div.className || '').substring(0, 80),
                    childCount: div.children.length,
                    textPreview: div.textContent.substring(0, 100).trim(),
                });
            }
        }

        // 方法2：找 input (可能是动态渲染的)
        const inputs = document.querySelectorAll('input, textarea');
        for (const inp of inputs) {
            const rect = inp.getBoundingClientRect();
            results.push({
                type: 'input',
                tag: inp.tagName,
                inputType: inp.type,
                placeholder: inp.placeholder || '',
                position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                id: inp.id,
            });
        }

        return results;
    }''')

    for item in panel_info:
        if item['type'] == 'panel':
            print(f"  📦 面板: <{item['tag']}> at {item['position']} size={item['size']} z-index={item['zIndex']} pos={item['cssPosition']}")
            print(f"      class='{item['className']}' children={item['childCount']}")
            print(f"      text: {item['textPreview'][:60]}...")
        else:
            print(f"  📝 Input: <{item['tag']}> type={item['inputType']} placeholder='{item['placeholder']}' id='{item['id']}' at {item['position']}")

    pw.stop()
    print("\n✅ 探测完成")


if __name__ == "__main__":
    main()
