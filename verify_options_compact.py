import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await p.browser.new_page() if hasattr(p, 'browser') else await browser.new_page()
        await page.goto('http://localhost:3000/options')
        await asyncio.sleep(5)
        await page.screenshot(path='/home/jules/verification/options_compact_v2.png', full_page=True)
        await browser.close()

asyncio.run(main())
