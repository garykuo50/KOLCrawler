import sys
import os
import asyncio
import re
import pandas as pd
from playwright.async_api import async_playwright

# ==========================================
# ⚙️ 爬蟲設定區 (Settings)
# ==========================================
# 請在這裡修改您想要抓取的創作者數量！
# 例如：設定為 30 就是抓取前 30 名 KOL，設定為 50 就是抓取前 50 名。
# 注意：抓取 30 名大約需要花費 3~5 分鐘的時間。
MAX_CHANNELS_TO_SCRAPE = 200 
# ==========================================

def parse_views_str(view_str):
    view_str = view_str.upper().replace(',', '')
    if 'B' in view_str:
        return float(view_str.replace('B', '')) * 1000000000
    elif 'M' in view_str:
        return float(view_str.replace('M', '')) * 1000000
    elif 'K' in view_str:
        return float(view_str.replace('K', '')) * 1000
    else:
        return float(view_str)

def format_number(num):
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}K"
    return str(int(num))

async def main():
    print(f"啟動爬蟲，準備抓取「夜市美食」前 {MAX_CHANNELS_TO_SCRAPE} 名 KOL 資料...")
    os.makedirs('covers', exist_ok=True)
    
    async with async_playwright() as p:
        # Launch headless Chromium
        browser = await p.chromium.launch(headless=True)
        # Use en-US to make finding DOM elements like "subscribers" and "views" predictable
        context = await browser.new_context(locale='en-US', viewport={'width': 1280, 'height': 720})
        page = await context.new_page()

        print("正在前往 YouTube 搜尋結果...")
        await page.goto('https://www.youtube.com/results?search_query=夜市美食', wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)

        # Accept cookies if the popup appears
        try:
            btn = page.get_by_role("button", name="Accept all")
            if await btn.count() > 0:
                await btn.first.click()
        except Exception:
            pass

        # Scroll to load many videos
        print("正在向下捲動頁面以獲知更多影片...")
        for i in range(15):
            await page.keyboard.press("End")
            await page.wait_for_timeout(1000)

        # 這裡使用 dict 來確保頻道順序和 YouTube 搜尋結果「完全一致」
        channel_handles = dict()
        
        # 找出所有創作者的連結
        elements = await page.locator("a[href^='/@']").all()
        for el in elements:
            href = await el.get_attribute('href')
            if href:
                handle = href.split('/')[1] 
                channel_handles[f"/{handle}"] = True 

        print(f"總共在畫面上找到了 {len(channel_handles)} 個不重複的頻道。")
        
        results = []
        # 套用上方設定的抓取數量限制！
        channel_list = list(channel_handles.keys())[:MAX_CHANNELS_TO_SCRAPE]
        
        for i, handle in enumerate(channel_list):
            url = f"https://www.youtube.com{handle}"
            print(f"[{i+1}/{MAX_CHANNELS_TO_SCRAPE}] 處理中: {url}")
            
            creator = handle[2:] # Default
            subscribers = "Unknown"
            total_views = "Unknown"
            max_views = "Unknown"
            average_views = "Unknown"
            cover_path = ""
            
            try:
                # 1. Main Profile (Subscribers, Total Views, Screenshot)
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000) 
                
                try:
                    title_meta = await page.locator('meta[property="og:title"]').get_attribute('content', timeout=2000)
                    if title_meta: creator = title_meta
                except Exception:
                    pass

                safe_creator = re.sub(r'[\\/*?:"<>|]', "", creator).strip()
                if not safe_creator: safe_creator = handle.replace("/", "_")
                cover_path = f"covers/{safe_creator}.png"
                
                # Take screenshot of the channel page (Header/Cover area visible)
                await page.screenshot(path=cover_path)

                page_text = await page.locator('body').inner_text()
                sub_match = re.search(r'([\d\.]+[KMB]?)\s*subscribers', page_text, re.IGNORECASE)
                if sub_match:
                    subscribers = sub_match.group(1)
                
                try:
                    # Open about modal
                    await page.locator('page-header-view-model yt-description-preview-view-model, button[aria-label*="about this channel" i]').first.click(timeout=3000)
                    await page.wait_for_timeout(2000) 
                    dialog_text = await page.locator('yt-about-channel-view-model, tp-yt-paper-dialog, ytd-popup-container').inner_text(timeout=3000)
                    view_match = re.search(r'([\d,]+)\s*views', dialog_text, re.IGNORECASE)
                    if view_match:
                        total_views = view_match.group(1).replace(',', '') 
                except Exception:
                    pass
                
                # 2. Latest Videos (Average Views)
                try:
                    await page.goto(f"{url}/videos", wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(3000)
                    await page.keyboard.press("PageDown") # load top couple rows
                    await page.wait_for_timeout(1000)
                    
                    videos_text = await page.locator('body').inner_text(timeout=3000)
                    view_matches = re.findall(r'([\d\.]+[KMB]?)\s*views', videos_text, re.IGNORECASE)
                    
                    if view_matches:
                        view_numbers = [parse_views_str(v) for v in view_matches]
                        if len(view_numbers) > 0:
                            avg_numeric = sum(view_numbers) / len(view_numbers)
                            average_views = format_number(avg_numeric)
                except Exception as e:
                    print(f"  -> Error computing average views: {e}")

                # 3. Popular Videos (Max Views)
                try:
                    # Navigate to popular sort directly
                    await page.goto(f"{url}/videos?view=0&sort=p", wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(3000)
                    
                    videos_text_pop = await page.locator('body').inner_text(timeout=3000)
                    pop_match = re.search(r'([\d\.]+[KMB]?)\s*views', videos_text_pop, re.IGNORECASE)
                    if pop_match:
                        max_views_num = parse_views_str(pop_match.group(1))
                        max_views = format_number(max_views_num)
                except Exception as e:
                    print(f"  -> Error computing max views: {e}")

                results.append({
                    "Creator": creator,
                    "Subscribers": subscribers,
                    "Total Views": total_views,
                    "Max Views (Popular)": max_views,
                    "Average Views (Latest ~30)": average_views,
                    "Cover Path": cover_path,
                    "URL": url
                })
            except Exception as e:
                print(f"Error processing {handle}: {e}")
                
        df = pd.DataFrame(results)
        csv_path = "youtube_kol_list.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"資料已成功儲存至 {csv_path}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
