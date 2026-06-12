import sys
import os
import asyncio
import re
import csv
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import mysql.connector

from playwright.async_api import async_playwright

# ─────────────────────────────────────────
#  資料庫設定與讀寫
# ─────────────────────────────────────────
def load_config_md() -> dict:
    config_path = "config.md"
    default_cfg = {
        "host":     "192.168.11.217",
        "port":     3306,
        "user":     "root",
        "password": "@Gein27970802",
        "database": "kol_db",
        "charset":  "utf8mb4",
    }
    if not os.path.exists(config_path):
        save_config_md(default_cfg)
        return default_cfg
        
    cfg = dict(default_cfg)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
            host_m = re.search(r"-\s*\*\*Host\*\*:\s*([^\n]+)", content)
            port_m = re.search(r"-\s*\*\*Port\*\*:\s*([^\n]+)", content)
            user_m = re.search(r"-\s*\*\*User\*\*:\s*([^\n]+)", content)
            pass_m = re.search(r"-\s*\*\*Password\*\*:\s*([^\n]+)", content)
            db_m = re.search(r"-\s*\*\*Database\*\*:\s*([^\n]+)", content)
            
            if host_m: cfg["host"] = host_m.group(1).strip()
            if port_m:
                try:
                    cfg["port"] = int(port_m.group(1).strip())
                except ValueError:
                    pass
            if user_m: cfg["user"] = user_m.group(1).strip()
            if pass_m: cfg["password"] = pass_m.group(1).strip()
            if db_m: cfg["database"] = db_m.group(1).strip()
    except Exception as e:
        print(f"Error loading config.md: {e}")
    return cfg

def save_config_md(cfg: dict):
    config_path = "config.md"
    content = f"""# Database Configuration

- **Host**: {cfg.get('host', '192.168.11.217')}
- **Port**: {cfg.get('port', 3306)}
- **User**: {cfg.get('user', 'root')}
- **Password**: {cfg.get('password', '')}
- **Database**: {cfg.get('database', 'kol_db')}
"""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Error saving config.md: {e}")

# 載入資料庫設定
DB_CONFIG = load_config_md()

MAX_CHANNELS = 50   # 預設抓取上限

# ─────────────────────────────────────────
#  工具函式
# ─────────────────────────────────────────
def parse_views_str(view_str: str) -> float:
    s = view_str.upper().replace(",", "").replace(" ", "").strip()
    s = s.replace("次觀看", "").replace("觀看次數", "").replace("位訂閱者", "").replace("訂閱者", "")
    
    multiplier = 1.0
    if "B" in s or "億" in s:
        multiplier = 1_000_000_000
        s = s.replace("B", "").replace("億", "")
    elif "M" in s:
        multiplier = 1_000_000
        s = s.replace("M", "")
    elif "K" in s:
        multiplier = 1_000
        s = s.replace("K", "")
    elif "萬" in s:
        multiplier = 10_000
        s = s.replace("萬", "")
        
    try:
        val_match = re.search(r"([\d\.]+)", s)
        if val_match:
            return float(val_match.group(1)) * multiplier
        return 0.0
    except ValueError:
        return 0.0

def format_number(num: float) -> str:
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 10_000:
        return f"{num / 10_000:.1f}萬"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(int(num))

# ─────────────────────────────────────────
#  資料庫操作
# ─────────────────────────────────────────
def ensure_db():
    """建立資料庫與資料表（若不存在），並支援欄位升級"""
    cfg = dict(DB_CONFIG)
    cfg.pop("database", None)
    cfg["connection_timeout"] = 5
    conn = mysql.connector.connect(**cfg)
    cur = conn.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']} "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    conn.database = DB_CONFIG["database"]
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kol_records (
            id                    INT AUTO_INCREMENT PRIMARY KEY,
            keyword               VARCHAR(255)  NOT NULL,
            channel_name          VARCHAR(500)  NOT NULL,
            channel_url           VARCHAR(1000) NOT NULL,
            subscribers           VARCHAR(50)   DEFAULT NULL,
            avg_views             VARCHAR(50)   DEFAULT NULL,
            max_views             VARCHAR(50)   DEFAULT NULL,
            max_view_video_url    VARCHAR(1000) DEFAULT NULL,
            channel_total_views   VARCHAR(50)   DEFAULT NULL,
            joined_date           VARCHAR(50)   DEFAULT NULL,
            recorded_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_keyword     (keyword),
            INDEX idx_recorded_at (recorded_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    
    # 自動升級舊有資料表結構
    migrations = [
        ("max_view_video_url", "VARCHAR(1000) DEFAULT NULL"),
        ("channel_total_views", "VARCHAR(50) DEFAULT NULL"),
        ("joined_date", "VARCHAR(50) DEFAULT NULL")
    ]
    for col_name, col_type in migrations:
        try:
            cur.execute(f"ALTER TABLE kol_records ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass
            
    conn.commit()
    cur.close()
    conn.close()

def save_record(keyword, channel_name, channel_url,
                subscribers, avg_views, max_views,
                max_view_video_url, channel_total_views, joined_date):
    cfg = dict(DB_CONFIG)
    cfg["connection_timeout"] = 5
    conn = mysql.connector.connect(**cfg)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO kol_records
           (keyword, channel_name, channel_url, subscribers, avg_views, max_views,
            max_view_video_url, channel_total_views, joined_date, recorded_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (keyword, channel_name, channel_url,
         subscribers, avg_views, max_views,
         max_view_video_url, channel_total_views, joined_date,
         datetime.now())
    )
    conn.commit()
    cur.close()
    conn.close()

# ─────────────────────────────────────────
#  爬蟲核心（async）
# ─────────────────────────────────────────
async def crawl(keyword: str, max_ch: int,
                on_progress, on_result, on_done, on_error, is_stopped):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                locale="en-US",
                viewport={"width": 1280, "height": 720}
            )
            page = await ctx.new_page()

            on_progress(f"前往 YouTube 搜尋「{keyword}」...")
            search_url = f"https://www.youtube.com/results?search_query={keyword}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)

            # 接受 Cookie
            try:
                btn = page.get_by_role("button", name="Accept all")
                if await btn.count() > 0:
                    await btn.first.click()
            except Exception:
                pass

            # 向下捲動載入更多
            on_progress("捲動頁面以載入更多頻道...")
            for _ in range(15):
                if is_stopped():
                    break
                await page.keyboard.press("End")
                await page.wait_for_timeout(800)

            # 收集頻道 handle（去重，保序）
            channel_handles: dict[str, bool] = {}
            elements = await page.locator("a[href^='/@']").all()
            for el in elements:
                href = await el.get_attribute("href")
                if href:
                    handle = "/" + href.split("/")[1]
                    channel_handles[handle] = True

            total = min(len(channel_handles), max_ch)
            on_progress(f"找到 {len(channel_handles)} 個頻道，準備抓取前 {total} 個...")

            channel_list = list(channel_handles.keys())[:max_ch]

            for i, handle in enumerate(channel_list):
                if is_stopped():
                    on_progress("⏹ 已停止爬取。")
                    break

                url = f"https://www.youtube.com{handle}"
                on_progress(f"[{i+1}/{total}] 處理: {url}")

                creator = handle[2:]
                subscribers = "Unknown"
                avg_views = "Unknown"
                max_views = "Unknown"
                max_view_video_url = ""
                channel_total_views = "Unknown"
                joined_date = "Unknown"

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(2500)

                    # 頻道名稱
                    try:
                        title = await page.locator('meta[property="og:title"]').get_attribute("content", timeout=2000)
                        if title:
                            creator = title
                    except Exception:
                        pass

                    # 訂閱數
                    try:
                        page_text = await page.locator("body").inner_text()
                        sub_m = re.search(r"([\d\.]+[KMB萬]?)\s*(?:subscribers|訂閱者|位訂閱者)", page_text, re.IGNORECASE)
                        if sub_m:
                            subscribers = sub_m.group(1)
                    except Exception:
                        pass

                    # 點開「顯示更多」/ 關於，以抓取總觀看與加入日期
                    try:
                        about_selectors = [
                            'button[aria-label*="about this channel" i]',
                            'button[aria-label*="關於此頻道" i]',
                            'button[aria-label*="更多內容" i]',
                            'page-header-view-model yt-description-preview-view-model',
                            '#description-container',
                            '.yt-description-preview-view-model-truncated'
                        ]
                        clicked = False
                        for selector in about_selectors:
                            locator = page.locator(selector).first
                            if await locator.count() > 0 and await locator.is_visible():
                                # 使用 evaluate JS 點擊，防止被其它元素阻擋
                                await locator.evaluate("el => el.click()")
                                clicked = True
                                break
                        
                        if clicked:
                            # 等待對話框顯示並獲取其文字
                            dialog_selectors = [
                                'yt-about-channel-view-model',
                                'ytd-about-channel-renderer',
                                'tp-yt-paper-dialog',
                                'ytd-popup-container',
                                '#about-container'
                            ]
                            dialog_text = ""
                            for d_sel in dialog_selectors:
                                try:
                                    locator = page.locator(d_sel).first
                                    await locator.wait_for(state="visible", timeout=3000)
                                    dialog_text = await locator.inner_text()
                                    if dialog_text:
                                        break
                                except Exception:
                                    pass
                            
                            if dialog_text:
                                # 總觀看數
                                view_match = re.search(r'([\d,]+)\s*(?:views|次觀看|觀看)', dialog_text, re.IGNORECASE)
                                if not view_match:
                                    view_match = re.search(r'(?:觀看次數|觀看)[：:\s]+([\d,]+)', dialog_text, re.IGNORECASE)
                                if view_match:
                                    raw_v = view_match.group(1).replace(',', '')
                                    try:
                                        channel_total_views = format_number(float(raw_v))
                                    except ValueError:
                                        channel_total_views = view_match.group(1)
                                
                                # 加入日期
                                joined_match = re.search(r'(?:Joined|加入日期|於)\s*([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{4}/\d{2}/\d{2}|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)', dialog_text, re.IGNORECASE)
                                if joined_match:
                                    joined_date = joined_match.group(1)
                            
                            # 關閉彈窗
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(500)
                    except Exception as e:
                        print(f"Error getting about info: {e}")

                    # 2. 平均觀看（最近影片）
                    try:
                        await page.goto(f"{url}/videos", wait_until="domcontentloaded", timeout=15000)
                        await page.wait_for_timeout(2500)
                        await page.keyboard.press("PageDown")
                        await page.wait_for_timeout(800)
                        vtext = await page.locator("body").inner_text(timeout=3000)
                        vmatches = re.findall(r"([\d\.]+[KMB萬]?)\s*(?:views|次觀看|觀看次數|觀看)", vtext, re.IGNORECASE)
                        if vmatches:
                            nums = [parse_views_str(v) for v in vmatches]
                            avg_views = format_number(sum(nums) / len(nums))
                    except Exception:
                        pass

                    # 3. 掃描所有影片資訊以找到最高觀看數及 URL
                    try:
                        popular_clicked = False
                        # 嘗試點擊 "Popular" 或 "熱門" 標籤
                        popular_selectors = [
                            'yt-formatted-string:has-text("Popular")',
                            'yt-formatted-string:has-text("熱門")',
                            'a:has-text("Popular")',
                            'a:has-text("熱門")',
                            'role=tab[name="Popular"]',
                            'role=tab[name="熱門"]'
                        ]
                        for sel in popular_selectors:
                            try:
                                locator = page.locator(sel).first
                                if await locator.count() > 0 and await locator.is_visible():
                                    await locator.click(timeout=3000)
                                    popular_clicked = True
                                    await page.wait_for_timeout(2000)
                                    break
                            except Exception:
                                pass
                        
                        if not popular_clicked:
                            await page.goto(f"{url}/videos?view=0&sort=p", wait_until="domcontentloaded", timeout=15000)
                            await page.wait_for_timeout(2500)
                        
                        # 等待影片連結加載完成，確保網頁已渲染出影片列表
                        try:
                            await page.wait_for_selector("a#video-title-link", timeout=8000)
                        except Exception:
                            pass

                        # 捲動幾次以載入更多熱門影片
                        for _ in range(3):
                            if is_stopped():
                                break
                            await page.keyboard.press("PageDown")
                            await page.wait_for_timeout(600)
                            
                        # 再次等待，確保滾動載入的內容就緒
                        try:
                            await page.wait_for_selector("a#video-title-link", timeout=3000)
                        except Exception:
                            pass

                        grid_selectors = ["ytd-rich-grid-media", "ytd-grid-video-renderer", "ytd-rich-item-renderer", "ytd-video-renderer"]
                        video_cards = []
                        for sel in grid_selectors:
                            elements = await page.locator(sel).all()
                            if len(elements) > 0:
                                video_cards = elements
                                break
                                
                        if not video_cards:
                            # 備用方案：如果找不到容器，直接找所有影片連結作為 card
                            video_cards = await page.locator("a#video-title-link").all()

                        if video_cards:
                            max_num = -1.0
                            best_url = ""
                            best_views_str = "Unknown"
                            
                            for card in video_cards:
                                try:
                                    card_tag = await card.evaluate("el => el.tagName.toLowerCase()")
                                    if card_tag == "a":
                                        href = await card.get_attribute("href")
                                        card_url = f"https://www.youtube.com{href}" if href else ""
                                        
                                        # 使用 JS 往上找父容器並尋找觀看數，避免定位不到
                                        card_views_str = await card.evaluate("""el => {
                                            let parent = el.closest('ytd-rich-grid-media, ytd-grid-video-renderer, ytd-rich-item-renderer, ytd-video-renderer, ytd-compact-video-renderer');
                                            if (!parent) parent = el.parentElement.parentElement;
                                            if (parent) {
                                                let text = parent.innerText;
                                                let lines = text.split('\\n');
                                                for (let line of lines) {
                                                    if (line.toLowerCase().includes('view') || line.includes('觀看')) {
                                                        return line;
                                                    }
                                                }
                                            }
                                            return '';
                                        }""")
                                    else:
                                        link_el = card.locator("a#video-title-link")
                                        if await link_el.count() > 0:
                                            href = await link_el.first.get_attribute("href")
                                            card_url = f"https://www.youtube.com{href}" if href else ""
                                        else:
                                            continue
                                            
                                        meta_items = await card.locator("span.inline-metadata-item, #metadata-line span").all()
                                        card_views_str = ""
                                        for meta in meta_items:
                                            txt = await meta.inner_text()
                                            if any(k in txt.lower() for k in ["view", "觀看"]):
                                                card_views_str = txt
                                                break
                                                
                                    if card_views_str and card_url:
                                        numeric_views = parse_views_str(card_views_str)
                                        if numeric_views > max_num:
                                            max_num = numeric_views
                                            best_url = card_url
                                            best_views_str = format_number(numeric_views)
                                except Exception as ex:
                                    print(f"Error parsing card: {ex}")
                                    
                            if max_num >= 0:
                                max_views = best_views_str
                                max_view_video_url = best_url
                    except Exception as e:
                        print(f"Error scanning videos: {e}")

                    on_result(keyword, creator, url,
                              subscribers, avg_views, max_views,
                              max_view_video_url, channel_total_views, joined_date)

                except Exception as e:
                    on_progress(f"  ⚠ 跳過 {handle}: {e}")

            await browser.close()
            on_done()

    except Exception as e:
        on_error(str(e))

# ─────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube KOL Crawler")
        self.geometry("1150x700")
        self.resizable(True, True)
        self._build_ui()
        self._crawling = False

    def _build_ui(self):
        # ── 頂部設定列 ──────────────────────────
        top = tk.Frame(self, padx=10, pady=8)
        top.pack(fill="x")

        tk.Label(top, text="關鍵字：", font=("Microsoft JhengHei", 11)).pack(side="left")
        self.kw_var = tk.StringVar()
        tk.Entry(top, textvariable=self.kw_var,
                 font=("Microsoft JhengHei", 11), width=20).pack(side="left", padx=(0, 12))

        tk.Label(top, text="最多頻道：", font=("Microsoft JhengHei", 11)).pack(side="left")
        self.max_var = tk.IntVar(value=MAX_CHANNELS)
        tk.Spinbox(top, from_=5, to=500, textvariable=self.max_var,
                   width=6, font=("Microsoft JhengHei", 11)).pack(side="left", padx=(0, 12))

        self.btn_start = tk.Button(
            top, text="▶  開始爬取",
            font=("Microsoft JhengHei", 11, "bold"),
            bg="#2196F3", fg="white", padx=12,
            command=self._on_start
        )
        self.btn_start.pack(side="left")

        self.btn_stop = tk.Button(
            top, text="■  停止",
            font=("Microsoft JhengHei", 11),
            bg="#f44336", fg="white", padx=12,
            state="disabled",
            command=self._on_stop
        )
        self.btn_stop.pack(side="left", padx=(6, 0))

        # 資料庫設定按鈕
        self.btn_db_settings = tk.Button(
            top, text="⚙️ 資料庫設定",
            font=("Microsoft JhengHei", 11),
            bg="#607D8B", fg="white", padx=12,
            command=self._on_open_db_settings
        )
        self.btn_db_settings.pack(side="left", padx=(12, 0))

        # 匯出 CSV 按鈕
        self.btn_export_csv = tk.Button(
            top, text="📥 匯出 CSV",
            font=("Microsoft JhengHei", 11, "bold"),
            bg="#4CAF50", fg="white", padx=12,
            command=self._on_export_csv
        )
        self.btn_export_csv.pack(side="left", padx=(12, 0))

        # ── 進度條 ──────────────────────────────
        self.progress_var = tk.StringVar(value="就緒")
        tk.Label(self, textvariable=self.progress_var,
                 font=("Microsoft JhengHei", 9),
                 anchor="w", fg="#555").pack(fill="x", padx=10)

        self.pbar = ttk.Progressbar(self, mode="indeterminate")
        self.pbar.pack(fill="x", padx=10, pady=(0, 4))

        # ── 結果表格 ─────────────────────────────
        cols = ("關鍵字", "頻道名稱", "訂閱數", "平均觀看", "最高觀看", "最高觀看影片網址", "總觀看數", "加入日期", "紀錄時間", "頻道網址")
        frame = tk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        vsb = ttk.Scrollbar(frame, orient="vertical")
        hsb = ttk.Scrollbar(frame, orient="horizontal")

        self.tree = ttk.Treeview(
            frame, columns=cols, show="headings",
            yscrollcommand=vsb.set, xscrollcommand=hsb.set
        )
        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)

        col_widths = [90, 150, 80, 90, 90, 180, 90, 110, 140, 180]
        for col, w in zip(cols, col_widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, minwidth=60)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        # ── 狀態列 ──────────────────────────────
        self.status_var = tk.StringVar(value="共 0 筆")
        tk.Label(self, textvariable=self.status_var,
                 font=("Microsoft JhengHei", 9),
                 anchor="w", fg="#333").pack(fill="x", padx=10, pady=(0, 4))

        self._row_count = 0

    # ── 事件 ────────────────────────────────────
    def _on_open_db_settings(self):
        settings_win = tk.Toplevel(self)
        settings_win.title("資料庫設定 (MariaDB/MySQL)")
        settings_win.geometry("450x300")
        settings_win.resizable(False, False)
        settings_win.grab_set()  # Make it modal

        # Host
        tk.Label(settings_win, text="主機 (Host):", font=("Microsoft JhengHei", 10)).grid(row=0, column=0, padx=20, pady=10, sticky="e")
        host_var = tk.StringVar(value=DB_CONFIG["host"])
        tk.Entry(settings_win, textvariable=host_var, width=25, font=("Microsoft JhengHei", 10)).grid(row=0, column=1, padx=10, pady=10)

        # Port
        tk.Label(settings_win, text="埠號 (Port):", font=("Microsoft JhengHei", 10)).grid(row=1, column=0, padx=20, pady=10, sticky="e")
        port_var = tk.StringVar(value=str(DB_CONFIG["port"]))
        tk.Entry(settings_win, textvariable=port_var, width=25, font=("Microsoft JhengHei", 10)).grid(row=1, column=1, padx=10, pady=10)

        # User
        tk.Label(settings_win, text="帳號 (User):", font=("Microsoft JhengHei", 10)).grid(row=2, column=0, padx=20, pady=10, sticky="e")
        user_var = tk.StringVar(value=DB_CONFIG["user"])
        tk.Entry(settings_win, textvariable=user_var, width=25, font=("Microsoft JhengHei", 10)).grid(row=2, column=1, padx=10, pady=10)

        # Password
        tk.Label(settings_win, text="密碼 (Password):", font=("Microsoft JhengHei", 10)).grid(row=3, column=0, padx=20, pady=10, sticky="e")
        pass_var = tk.StringVar(value=DB_CONFIG["password"])
        tk.Entry(settings_win, textvariable=pass_var, show="*", width=25, font=("Microsoft JhengHei", 10)).grid(row=3, column=1, padx=10, pady=10)

        # Database
        tk.Label(settings_win, text="資料庫 (DB):", font=("Microsoft JhengHei", 10)).grid(row=4, column=0, padx=20, pady=10, sticky="e")
        db_var = tk.StringVar(value=DB_CONFIG["database"])
        tk.Entry(settings_win, textvariable=db_var, width=25, font=("Microsoft JhengHei", 10)).grid(row=4, column=1, padx=10, pady=10)

        btn_frame = tk.Frame(settings_win)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=15)

        def test_conn():
            try:
                port_val = int(port_var.get().strip())
            except ValueError:
                messagebox.showerror("錯誤", "埠號必須是數字！", parent=settings_win)
                return
            
            test_cfg = {
                "host": host_var.get().strip(),
                "port": port_val,
                "user": user_var.get().strip(),
                "password": pass_var.get(),
                "charset": "utf8mb4",
                "connection_timeout": 5
            }
            
            btn_test.config(state="disabled", text="連線中...")
            settings_win.update()

            def run_test():
                try:
                    conn = mysql.connector.connect(**test_cfg)
                    cur = conn.cursor()
                    cur.execute(f"CREATE DATABASE IF NOT EXISTS {db_var.get().strip()} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                    cur.close()
                    conn.close()
                    settings_win.after(0, lambda: messagebox.showinfo("成功", "連線與資料庫初始化成功！", parent=settings_win))
                except Exception as ex:
                    err = str(ex)
                    settings_win.after(0, lambda: messagebox.showerror("連線失敗", f"無法連線：\n{err}", parent=settings_win))
                finally:
                    settings_win.after(0, lambda: btn_test.config(state="normal", text="測試連線"))

            threading.Thread(target=run_test, daemon=True).start()

        def save_conn():
            try:
                port_val = int(port_var.get().strip())
            except ValueError:
                messagebox.showerror("錯誤", "埠號必須是數字！", parent=settings_win)
                return
            
            DB_CONFIG["host"] = host_var.get().strip()
            DB_CONFIG["port"] = port_val
            DB_CONFIG["user"] = user_var.get().strip()
            DB_CONFIG["password"] = pass_var.get()
            DB_CONFIG["database"] = db_var.get().strip()
            
            save_config_md(DB_CONFIG)
            messagebox.showinfo("成功", "設定已儲存並寫入 config.md！", parent=settings_win)
            settings_win.destroy()

        btn_test = tk.Button(btn_frame, text="測試連線", font=("Microsoft JhengHei", 9, "bold"), bg="#4CAF50", fg="white", padx=10, command=test_conn)
        btn_test.pack(side="left", padx=10)

        btn_save = tk.Button(btn_frame, text="儲存設定", font=("Microsoft JhengHei", 9, "bold"), bg="#2196F3", fg="white", padx=10, command=save_conn)
        btn_save.pack(side="left", padx=10)

    def _on_export_csv(self):
        items = self.tree.get_children()
        if not items:
            messagebox.showwarning("提示", "目前沒有資料可以匯出！")
            return
            
        from tkinter import filedialog
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            title="選擇儲存路徑",
            initialfile=f"youtube_kol_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not file_path:
            return
            
        try:
            cols = self.tree["columns"]
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(cols)
                for item in items:
                    writer.writerow(self.tree.item(item)["values"])
                    
            messagebox.showinfo("成功", f"資料已成功匯出至：\n{file_path}")
        except Exception as e:
            messagebox.showerror("錯誤", f"匯出失敗：\n{e}")

    def _on_start(self):
        kw = self.kw_var.get().strip()
        if not kw:
            messagebox.showwarning("提示", "請輸入關鍵字！")
            return
        if self._crawling:
            return

        try:
            ensure_db()
        except Exception as e:
            messagebox.showerror("資料庫錯誤", f"無法連線到 MariaDB/MySQL：\n{e}")
            return

        self._crawling = True
        self._stop_flag = False
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_db_settings.config(state="disabled")
        self.btn_export_csv.config(state="disabled")
        self.pbar.start(12)

        max_ch = self.max_var.get()

        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                crawl(
                    kw, max_ch,
                    on_progress=self._on_progress,
                    on_result=self._on_result,
                    on_done=self._on_done,
                    on_error=self._on_error,
                    is_stopped=lambda: self._stop_flag
                )
            )
            loop.close()

        threading.Thread(target=run, daemon=True).start()

    def _on_stop(self):
        self._stop_flag = True
        self._finish()

    def _finish(self):
        self._crawling = False
        self.pbar.stop()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_db_settings.config(state="normal")
        self.btn_export_csv.config(state="normal")

    # ── Callbacks ──
    def _on_progress(self, msg: str):
        self.after(0, lambda: self.progress_var.set(msg))

    def _on_result(self, keyword, creator, url,
                   subscribers, avg_views, max_views,
                   max_view_video_url, channel_total_views, joined_date):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            save_record(keyword, creator, url,
                        subscribers, avg_views, max_views,
                        max_view_video_url, channel_total_views, joined_date)
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda: self.progress_var.set(f"⚠ DB 寫入失敗: {err_msg}"))

        def _insert():
            self.tree.insert(
                "", "end",
                values=(keyword, creator, subscribers,
                        avg_views, max_views, max_view_video_url,
                        channel_total_views, joined_date, now, url)
            )
            self._row_count += 1
            self.status_var.set(f"共 {self._row_count} 筆")

        self.after(0, _insert)

    def _on_done(self):
        self.after(0, lambda: self.progress_var.set("✅ 爬取完成！"))
        self.after(0, self._finish)

    def _on_error(self, msg: str):
        self.after(0, lambda: messagebox.showerror("錯誤", msg))
        self.after(0, self._finish)

# ─────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
