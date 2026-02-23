import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()
        await page.goto('http://127.0.0.1:3000/options')
        await asyncio.sleep(5)
        # Check for vertical scrollbar
        has_scroll = await page.evaluate("document.documentElement.scrollHeight > document.documentElement.clientHeight")
        print(f"Has vertical scroll: {has_scroll}")
        await page.screenshot(path='options_single_page_final.png')
        await browser.close()

asyncio.run(main())
