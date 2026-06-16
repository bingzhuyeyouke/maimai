"""快速验证：截图看脉脉发帖页话题选择效果"""

import time
from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
MAIMAI_URL = "https://maimai.cn/community/home/recommended"


def main():
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]

    # 找脉脉页面
    page = None
    for pg in context.pages:
        if "maimai.cn" in pg.url and not pg.is_closed():
            page = pg
            break

    if not page:
        page = context.new_page()
        page.goto(MAIMAI_URL, wait_until="domcontentloaded", timeout=15000)
        time.sleep(5)

    print(f"当前页面: {page.url}")

    # 截图1：当前状态
    page.screenshot(path="/tmp/maimai_step1_current.png")
    print("截图1: 当前页面状态 → /tmp/maimai_step1_current.png")

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
    print(f"点击添加话题按钮: {clicked}")
    time.sleep(2)

    # 截图2：弹出面板
    page.screenshot(path="/tmp/maimai_step2_popup.png")
    print("截图2: 弹出面板 → /tmp/maimai_step2_popup.png")

    # 探测弹出面板的 DOM 结构
    popup_info = page.evaluate('''() => {
        const results = [];

        // 找搜索框
        const searchInputs = document.querySelectorAll('input[placeholder="搜索"], input[placeholder*="搜索"]');
        for (const inp of searchInputs) {
            const rect = inp.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                results.push({
                    type: 'search_input',
                    placeholder: inp.placeholder,
                    position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                    size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                });
            }
        }

        // 找弹出面板中的可点击项
        // 搜索结果通常在弹出面板里，按位置判断（弹出面板在按钮下方）
        const all = document.querySelectorAll('span, div, li, p');
        for (const el of all) {
            const t = (el.textContent || '').trim();
            const rect = el.getBoundingClientRect();
            // 弹出面板在页面中间偏下，元素可见且文字适中
            if (t.length > 2 && t.length < 40 && rect.width > 100 && rect.height > 10 && rect.height < 60
                && rect.y > 300 && rect.y < 700) {
                results.push({
                    type: 'clickable_item',
                    text: t,
                    tag: el.tagName,
                    position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                    size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                    className: (el.className || '').toString().substring(0, 60),
                });
            }
        }

        return results;
    }''')

    print(f"\n弹出面板结构 ({len(popup_info)} 个元素):")
    for item in popup_info[:15]:
        if item['type'] == 'search_input':
            print(f"  🔍 搜索框: placeholder='{item['placeholder']}' at {item['position']} size={item['size']}")
        else:
            print(f"  📎 {item['tag']} '{item['text'][:30]}' at {item['position']} size={item['size']} class='{item.get('className', '')}'")

    # 在搜索框输入 "我来爆个料"
    search_input = page.locator('input[placeholder="搜索"]')
    if search_input.count() > 0:
        search_input.last.click()
        time.sleep(0.3)
        search_input.last.fill("我来爆个料")
        print("\n已输入搜索关键词: 我来爆个料")
        time.sleep(2)

        # 截图3：搜索结果
        page.screenshot(path="/tmp/maimai_step3_search_results.png")
        print("截图3: 搜索结果 → /tmp/maimai_step3_search_results.png")

        # 探测搜索结果
        search_results = page.evaluate('''() => {
            const results = [];
            const all = document.querySelectorAll('span, div, li, p');
            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (t.length > 2 && t.length < 40 && rect.width > 100 && rect.height > 10 && rect.height < 60
                    && rect.y > 300 && rect.y < 700) {
                    results.push({
                        text: t,
                        tag: el.tagName,
                        position: `${Math.round(rect.x)},${Math.round(rect.y)}`,
                        className: (el.className || '').toString().substring(0, 60),
                    });
                }
            }
            return results;
        }''')

        print(f"\n搜索结果 ({len(search_results)} 个):")
        for item in search_results[:15]:
            contains_topic = '爆个料' in item['text']
            marker = " ⭐" if contains_topic else ""
            print(f"  {item['tag']} '{item['text'][:35]}' at {item['position']} class='{item.get('className', '')}'{marker}")

    pw.stop()
    print("\n✅ 探测完成")


if __name__ == "__main__":
    main()
