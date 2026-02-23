import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('http://localhost:3000')
        await asyncio.sleep(5)
        await page.screenshot(path='/home/jules/verification/main_dashboard_volume.png')
        await browser.close()

asyncio.run(main())
