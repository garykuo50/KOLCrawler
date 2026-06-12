import sys
import os
import asyncio
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import mysql.connector

from playwright.async_api import async_playwright

# ─────────────────────────────────────────
#  資料庫設定
# ─────────────────────────────────────────
DB_CONFIG = {
    "host":     "192.168.11.217",
    "port":     3306,
    "user":     "root",
    "password": "@Gein27970802",
    "database": "kol_db",
    "charset":  "utf8mb4",
}

MAX_CHANNELS = 50   # 預設抓取上限（可在 GUI 調整）

# ─────────────────────────────────────────
#  工具函式
# ─────────────────────────────────────────
def parse_views_str(view_str: str) -> float:
    s = view_str.upper().replace(",", "").strip()
    if "B" in s:
        return float(s.replace("B", "")) * 1_000_000_000
    elif "M" in s:
        return float(s.replace("M", "")) * 1_000_000
    elif "K" in s:
        return float(s.replace("K", "")) * 1_000
    else:
        try:
            return float(s)
        except ValueError:
            return 0.0

def format_number(num: float) -> str:
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(int(num))

# ─────────────────────────────────────────
#  資料庫操作
# ─────────────────────────────────────────
def ensure_db():
    """建立資料庫與資料表（若不存在）"""
    cfg = dict(DB_CONFIG)
    cfg.pop("database", None)          # 先不指定 DB，才能建立它
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
            id            INT AUTO_INCREMENT PRIMARY KEY,
            keyword       VARCHAR(255)  NOT NULL,
            channel_name  VARCHAR(500)  NOT NULL,
            channel_url   VARCHAR(1000) NOT NULL,
            subscribers   VARCHAR(50)   DEFAULT NULL,
            avg_views     VARCHAR(50)   DEFAULT NULL,
            max_views     VARCHAR(50)   DEFAULT NULL,
            recorded_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_keyword     (keyword),
            INDEX idx_recorded_at (recorded_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    conn.commit()
    cur.close()
    conn.close()

def save_record(keyword, channel_name, channel_url,
                subscribers, avg_views, max_views):
    cfg = dict(DB_CONFIG)
    cfg["connection_timeout"] = 5
    conn = mysql.connector.connect(**cfg)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO kol_records
           (keyword, channel_name, channel_url, subscribers, avg_views, max_views, recorded_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (keyword, channel_name, channel_url,
         subscribers, avg_views, max_views,
         datetime.now())
    )
    conn.commit()
    cur.close()
    conn.close()

# ─────────────────────────────────────────
#  爬蟲核心（async）
# ─────────────────────────────────────────
async def crawl(keyword: str, max_ch: int,
                on_progress, on_result, on_done, on_error):
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
                url = f"https://www.youtube.com{handle}"
                on_progress(f"[{i+1}/{total}] 處理: {url}")

                creator    = handle[2:]
                subscribers = "Unknown"
                avg_views   = "Unknown"
                max_views   = "Unknown"

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(2500)

                    # 頻道名稱
                    try:
                        title = await page.locator(
                            'meta[property="og:title"]'
                        ).get_attribute("content", timeout=2000)
                        if title:
                            creator = title
                    except Exception:
                        pass

                    # 訂閱數
                    page_text = await page.locator("body").inner_text()
                    sub_m = re.search(
                        r"([\d\.]+[KMB]?)\s*subscribers",
                        page_text, re.IGNORECASE
                    )
                    if sub_m:
                        subscribers = sub_m.group(1)

                    # 平均觀看（最近影片）
                    try:
                        await page.goto(
                            f"{url}/videos",
                            wait_until="domcontentloaded", timeout=15000
                        )
                        await page.wait_for_timeout(2500)
                        await page.keyboard.press("PageDown")
                        await page.wait_for_timeout(800)
                        vtext = await page.locator("body").inner_text(timeout=3000)
                        vmatches = re.findall(
                            r"([\d\.]+[KMB]?)\s*views",
                            vtext, re.IGNORECASE
                        )
                        if vmatches:
                            nums = [parse_views_str(v) for v in vmatches]
                            avg_views = format_number(sum(nums) / len(nums))
                    except Exception:
                        pass

                    # 最高觀看（熱門影片）
                    try:
                        await page.goto(
                            f"{url}/videos?view=0&sort=p",
                            wait_until="domcontentloaded", timeout=15000
                        )
                        await page.wait_for_timeout(2500)
                        ptxt = await page.locator("body").inner_text(timeout=3000)
                        pm = re.search(
                            r"([\d\.]+[KMB]?)\s*views",
                            ptxt, re.IGNORECASE
                        )
                        if pm:
                            max_views = format_number(parse_views_str(pm.group(1)))
                    except Exception:
                        pass

                    on_result(keyword, creator, url,
                              subscribers, avg_views, max_views)

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
        self.geometry("1000x680")
        self.resizable(True, True)
        self._build_ui()
        self._crawling = False

    def _build_ui(self):
        # ── 資料庫設定區 ──────────────────────────
        db_frame = tk.LabelFrame(self, text=" 資料庫設定 (MariaDB/MySQL) ", font=("Microsoft JhengHei", 10, "bold"), padx=10, pady=8)
        db_frame.pack(fill="x", padx=10, pady=(10, 5))

        tk.Label(db_frame, text="主機(Host)：", font=("Microsoft JhengHei", 9)).grid(row=0, column=0, sticky="w")
        self.db_host_var = tk.StringVar(value=DB_CONFIG["host"])
        tk.Entry(db_frame, textvariable=self.db_host_var, width=15, font=("Microsoft JhengHei", 9)).grid(row=0, column=1, padx=(0, 10))

        tk.Label(db_frame, text="埠號(Port)：", font=("Microsoft JhengHei", 9)).grid(row=0, column=2, sticky="w")
        self.db_port_var = tk.StringVar(value=str(DB_CONFIG["port"]))
        tk.Entry(db_frame, textvariable=self.db_port_var, width=6, font=("Microsoft JhengHei", 9)).grid(row=0, column=3, padx=(0, 10))

        tk.Label(db_frame, text="帳號(User)：", font=("Microsoft JhengHei", 9)).grid(row=0, column=4, sticky="w")
        self.db_user_var = tk.StringVar(value=DB_CONFIG["user"])
        tk.Entry(db_frame, textvariable=self.db_user_var, width=10, font=("Microsoft JhengHei", 9)).grid(row=0, column=5, padx=(0, 10))

        tk.Label(db_frame, text="密碼(Password)：", font=("Microsoft JhengHei", 9)).grid(row=0, column=6, sticky="w")
        self.db_pass_var = tk.StringVar(value=DB_CONFIG["password"])
        tk.Entry(db_frame, textvariable=self.db_pass_var, show="*", width=12, font=("Microsoft JhengHei", 9)).grid(row=0, column=7, padx=(0, 10))

        tk.Label(db_frame, text="資料庫(DB)：", font=("Microsoft JhengHei", 9)).grid(row=0, column=8, sticky="w")
        self.db_name_var = tk.StringVar(value=DB_CONFIG["database"])
        tk.Entry(db_frame, textvariable=self.db_name_var, width=12, font=("Microsoft JhengHei", 9)).grid(row=0, column=9, padx=(0, 10))

        self.btn_test_db = tk.Button(
            db_frame, text="測試連線",
            font=("Microsoft JhengHei", 9, "bold"),
            bg="#4CAF50", fg="white", padx=8,
            command=self._on_test_connection
        )
        self.btn_test_db.grid(row=0, column=10, padx=(10, 0))

        # ── 頂部設定列 ──────────────────────────
        top = tk.Frame(self, padx=10, pady=8)
        top.pack(fill="x")

        tk.Label(top, text="關鍵字：", font=("Microsoft JhengHei", 11)).pack(side="left")
        self.kw_var = tk.StringVar()
        tk.Entry(top, textvariable=self.kw_var,
                 font=("Microsoft JhengHei", 11), width=26).pack(side="left", padx=(0, 12))

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

        # ── 進度條 ──────────────────────────────
        self.progress_var = tk.StringVar(value="就緒")
        tk.Label(self, textvariable=self.progress_var,
                 font=("Microsoft JhengHei", 9),
                 anchor="w", fg="#555").pack(fill="x", padx=10)

        self.pbar = ttk.Progressbar(self, mode="indeterminate")
        self.pbar.pack(fill="x", padx=10, pady=(0, 4))

        # ── 結果表格 ─────────────────────────────
        cols = ("關鍵字", "頻道名稱", "訂閱數", "平均觀看", "最高觀看", "紀錄時間", "頻道網址")
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

        col_widths = [90, 200, 80, 90, 90, 140, 280]
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
    def _update_db_config_from_gui(self) -> bool:
        try:
            port_val = int(self.db_port_var.get().strip())
        except ValueError:
            messagebox.showerror("錯誤", "埠號必須是數字！")
            return False
            
        DB_CONFIG["host"] = self.db_host_var.get().strip()
        DB_CONFIG["port"] = port_val
        DB_CONFIG["user"] = self.db_user_var.get().strip()
        DB_CONFIG["password"] = self.db_pass_var.get()
        DB_CONFIG["database"] = self.db_name_var.get().strip()
        return True

    def _on_test_connection(self):
        if not self._update_db_config_from_gui():
            return

        self.btn_test_db.config(state="disabled", text="連線中...")
        self.update()

        def test_thread():
            try:
                cfg = dict(DB_CONFIG)
                cfg.pop("database", None)
                cfg["connection_timeout"] = 5
                conn = mysql.connector.connect(**cfg)
                
                # Check / create database
                cur = conn.cursor()
                cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                conn.database = DB_CONFIG['database']
                cur.close()
                conn.close()
                
                self.after(0, lambda: messagebox.showinfo("成功", "資料庫連線與初始化成功！"))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: messagebox.showerror("連線失敗", f"無法連線到資料庫：\n{err_msg}"))
            finally:
                self.after(0, lambda: self.btn_test_db.config(state="normal", text="測試連線"))

        threading.Thread(target=test_thread, daemon=True).start()

    def _on_start(self):
        kw = self.kw_var.get().strip()
        if not kw:
            messagebox.showwarning("提示", "請輸入關鍵字！")
            return
        if self._crawling:
            return

        # 更新資料庫設定
        if not self._update_db_config_from_gui():
            return

        # 初始化 DB
        try:
            ensure_db()
        except Exception as e:
            messagebox.showerror("資料庫錯誤", f"無法連線到 MariaDB：\n{e}")
            return

        self._crawling = True
        self._stop_flag = False
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.pbar.start(12)

        max_ch = self.max_var.get()

        # 在獨立執行緒跑 asyncio loop
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

    # ── Callbacks（從背景執行緒安全回到 GUI 執行緒）──
    def _on_progress(self, msg: str):
        self.after(0, lambda: self.progress_var.set(msg))

    def _on_result(self, keyword, creator, url,
                   subscribers, avg_views, max_views):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 寫入資料庫
        try:
            save_record(keyword, creator, url,
                        subscribers, avg_views, max_views)
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda: self.progress_var.set(f"⚠ DB 寫入失敗: {err_msg}"))

        # 更新表格（主執行緒）
        def _insert():
            self.tree.insert(
                "", "end",
                values=(keyword, creator, subscribers,
                        avg_views, max_views, now, url)
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
