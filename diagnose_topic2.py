"""精确探测：点击 # 添加话题 后弹出面板的搜索框"""

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

    # 先导航到发帖页
    page.goto(MAIMAI_URL, wait_until="domcontentloaded", timeout=15000)
    time.sleep(3)

    # 记录点击前的 input 数量
    inputs_before = page.evaluate('''() => {
        return document.querySelectorAll('input').length;
    }''')
    print(f"点击前 input 数量: {inputs_before}")

    # 点击 # 添加话题
    clicked = page.evaluate('''() => {
        const all = document.querySelectorAll('span, div');
        for (const el of all) {
            const t = (el.textContent || '').trim();
            const rect = el.getBoundingClientRect();
            if ((t === '# 添加话题' || t === '添加话题') && rect.width > 0 && rect.width < 200 && rect.height < 50) {
                el.click();
                return t;
            }
        }
        return false;
    }''')
    print(f"点击添加话题: {clicked}")
    time.sleep(2)

    # 记录点击后的 input 数量和详细信息
    inputs_after = page.evaluate('''() => {
        const inputs = document.querySelectorAll('input');
        const results = [];
        for (const inp of inputs) {
            const rect = inp.getBoundingClientRect();
            results.push({
                type: inp.type,
                placeholder: inp.placeholder || '',
                name: inp.name || '',
                className: (inp.className || '').substring(0, 80),
                id: inp.id || '',
                accept: inp.accept || '',
                position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                visible: rect.width > 0 && rect.height > 0,
                parentClass: (inp.parentElement?.className || '').substring(0, 80),
                grandparentClass: (inp.parentElement?.parentElement?.className || '').substring(0, 80),
            });
        }
        return results;
    }''')
    print(f"\n点击后 input 数量: {len(inputs_after)}")
    for i, inp in enumerate(inputs_after):
        print(f"\n  Input [{i}]:")
        print(f"    type={inp['type']} placeholder='{inp['placeholder']}' name='{inp['name']}'")
        print(f"    position={inp['position']} size={inp['size']} visible={inp['visible']}")
        print(f"    class='{inp['className']}' id='{inp['id']}'")
        print(f"    parent='{inp['parentClass']}'")
        print(f"    grandparent='{inp['grandparentClass']}'")

    # 找弹出面板的搜索框（应该是新增的、在页面下半部分的 input）
    # 弹出面板通常在 y > 200 的位置
    popup_inputs = [inp for inp in inputs_after if inp['visible'] and int(inp['position'].split(',')[1]) > 200]
    print(f"\n位于页面下半部分的 input: {len(popup_inputs)}")
    for inp in popup_inputs:
        print(f"  placeholder='{inp['placeholder']}' at {inp['position']} type={inp['type']}")

    # 截图看弹出面板
    page.screenshot(path="/tmp/maimai_topic_popup.png")
    print("\n截图: /tmp/maimai_topic_popup.png")

    # 如果找到了弹出面板的搜索框，尝试输入
    if popup_inputs:
        target_input = popup_inputs[0]
        print(f"\n尝试在弹出搜索框输入: position={target_input['position']}")

        # 通过位置定位 input
        filled = page.evaluate('''() => {
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {
                const rect = inp.getBoundingClientRect();
                // 弹出面板的搜索框：在页面下半部分，且是 text 类型
                if (rect.y > 200 && rect.width > 50 && (inp.type === 'text' || inp.type === 'search' || !inp.type)) {
                    inp.focus();
                    inp.value = '我来爆个料';
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                    return { found: true, position: `${rect.x},${rect.y}`, placeholder: inp.placeholder };
                }
            }
            return { found: false };
        }''')
        print(f"填充结果: {filled}")
        time.sleep(2)

        # 截图看搜索结果
        page.screenshot(path="/tmp/maimai_topic_search.png")
        print("搜索结果截图: /tmp/maimai_topic_search.png")

        # 查看搜索结果
        results = page.evaluate('''() => {
            const items = [];
            // 找弹出面板中的话题结果
            // 结果通常在搜索框下方，有话题名称文字
            const all = document.querySelectorAll('span, div, li, p');
            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                // 弹出面板区域 y > 300, 结果项高度适中
                if (t.length > 3 && t.length < 40 && rect.width > 50 && rect.height > 10 && rect.height < 50
                    && rect.y > 350 && rect.y < 700 && rect.x > 300) {
                    items.push({
                        text: t,
                        tag: el.tagName,
                        position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                        size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                        className: (el.className || '').substring(0, 60),
                    });
                }
            }
            return items;
        }''')

        print(f"\n搜索结果区域元素 ({len(results)} 个):")
        seen = set()
        for item in results:
            if item['text'] not in seen:
                seen.add(item['text'])
                contains = '爆料' in item['text']
                marker = " ⭐⭐⭐" if contains else ""
                print(f"  {item['tag']} '{item['text'][:35]}' at {item['position']} {marker}")

    pw.stop()
    print("\n✅ 探测完成")


if __name__ == "__main__":
    main()
