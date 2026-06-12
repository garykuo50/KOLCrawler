import asyncio
import re
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 720}
        )
        page = await ctx.new_page()
        
        url = "https://www.youtube.com/@TVBSNEWS01"
        print(f"Going to {url}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)
        
        # Take initial screenshot
        await page.screenshot(path="debug_initial.png")
        
        # Print page title and header elements
        print(f"Page title: {await page.title()}")
        
        # Find potential tagline elements in DOM
        tagline_selectors = [
            'ytd-channel-tagline-renderer',
            'yt-description-preview-view-model',
            '#channel-tagline',
            '#description-container',
            '.yt-description-preview-view-model-truncated'
        ]
        print("\n--- Tagline Elements Found ---")
        for sel in tagline_selectors:
            loc = page.locator(sel)
            count = await loc.count()
            print(f"Selector '{sel}': count={count}")
            if count > 0:
                print(f"  Outer HTML: {await loc.first.evaluate('el => el.outerHTML.substring(0, 200)')}...")
                
        # Try native tagline click
        print("\nAttempting native tagline click...")
        clicked = False
        try:
            loc = page.locator('ytd-channel-tagline-renderer, yt-description-preview-view-model, #channel-tagline, #description-container').first
            if await loc.count() > 0:
                await loc.click(timeout=5000)
                clicked = True
                print("Native click succeeded!")
        except Exception as e:
            print(f"Native click failed: {e}")
        
        if not clicked:
            # Try text click
            print("Attempting text click...")
            for text_val in ["顯示更多", "... 顯示更多", "...more", "about this channel", "關於此頻道", "更多內容", "more"]:
                loc = page.get_by_text(text_val).first
                if await loc.count() > 0:
                    print(f"Found text element: '{text_val}', clicking...")
                    await loc.click(timeout=3000)
                    clicked = True
                    break
        
        print("Waiting for drawer/dialog to open...")
        await page.wait_for_timeout(3000)
        await page.screenshot(path="debug_after_click.png")
        
        # Print potential dialogs in DOM
        dialog_selectors = [
            'yt-about-channel-view-model',
            'ytd-about-channel-renderer',
            'tp-yt-paper-dialog',
            'ytd-popup-container',
            '#about-container',
            '[role="dialog"]'
        ]
        print("\n--- Dialog Elements Found ---")
        for sel in dialog_selectors:
            loc = page.locator(sel)
            count = await loc.count()
            print(f"Selector '{sel}': count={count}")
            if count > 0:
                print(f"  Visible: {await loc.first.is_visible()}")
                txt = await loc.first.inner_text()
                print(f"  Inner Text (len={len(txt)}):\n{txt[:500]}\n---")
                
        # Let's inspect the entire body inner text to see if the joined date / views are present anywhere
        body_text = await page.locator("body").inner_text()
        print("\n--- Searching for 'Joined' or 'views' or '觀看' or '加入' in body ---")
        joined_m = re.search(r'(Joined|加入|於|views|觀看).*?(\d{4})', body_text, re.IGNORECASE)
        if joined_m:
            print(f"Found match: {joined_m.group(0)}")
        else:
            print("No simple date/view pattern found in entire body text.")
            
        print("\nSaving page HTML...")
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(await page.content())
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
