#!/usr/bin/env python3
"""claude-dev-system 設定視窗（tkinter，Python 內建；Windows 之外用 `python installer/gui.py` 啟動）。

畫面只做三件事：顯示 gui_model.read_state() 讀到的真實狀態、讓使用者改表單、按「套用」時呼叫 gui_model.apply_form()。
所有邏輯在 installer/cds/gui_model.py（可測試）；這裡只有版面與事件。套用後一律重讀狀態，不信表單。
用法：python installer/gui.py [--claude-home 路徑]
"""
from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds import commands, gui_model as gm, web  # noqa: E402
from cds.paths import REPO, Layout, claude_home  # noqa: E402

MARK = {True: "✅", False: "❌", None: "⚠️"}
PY = Path(sys.executable).as_posix()


class App:
    def __init__(self, root: tk.Tk, lay: Layout):
        self.root, self.lay = root, lay
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.state: dict = {}
        self.form: gm.Form = gm.Form()
        self.key_vars: dict[str, tk.StringVar] = {}
        self.key_dirty: dict[str, bool] = {}
        self.key_status: dict[str, tk.StringVar] = {}
        self.mode_vars: dict[str, tk.StringVar] = {}
        self.mode_boxes: dict = {}
        self.server_vars: dict[str, tk.BooleanVar] = {}
        self.env_vars: dict[str, tk.StringVar] = {}
        root.title("claude-dev-system 設定")
        root.minsize(980, 720)
        # 預設全視窗：排版寬鬆、字清楚（使用者要求）；Windows 用 zoomed，其他平台用螢幕尺寸
        try:
            root.state("zoomed")
        except tk.TclError:
            root.geometry(f"{root.winfo_screenwidth() - 40}x{root.winfo_screenheight() - 80}+20+20")
        base_font = ("Microsoft JhengHei UI", 11) if sys.platform == "win32" else ("", 11)
        root.option_add("*Font", base_font)
        st = ttk.Style(root)
        for cls in (".", "TLabel", "TButton", "TCheckbutton", "TEntry", "TCombobox", "TSpinbox", "TLabelframe.Label"):
            st.configure(cls, font=base_font)
        self._build()
        self.refresh()
        root.protocol("WM_DELETE_WINDOW", self.on_close)  # 有未套用的變更時關閉要先問
        root.after(100, self._pump)

    def on_close(self):
        try:
            ch = gm.diff(self.state, self._collect())
        except Exception:  # noqa: BLE001
            ch = []
        if self.busy:
            if not messagebox.askyesno("關閉", "有工作正在執行，確定要關閉？"):
                return
        elif ch:
            ans = messagebox.askyesnocancel("有未套用的變更", f"有 {len(ch)} 項變更還沒套用：\n\n" + "\n".join("• " + c.text for c in ch[:12])
                                            + ("\n…" if len(ch) > 12 else "") + "\n\n要先套用嗎？\n是＝套用後關閉　否＝放棄變更關閉　取消＝回到視窗")
            if ans is None:
                return
            if ans:
                self._close_after_apply = True
                self.do_apply()
                return
        self.root.destroy()

    # ---------- 版面 ----------
    def _build(self):
        r = self.root
        top = ttk.Frame(r, padding=8)
        top.pack(fill="x")
        self.title_var = tk.StringVar()
        ttk.Label(top, textvariable=self.title_var, font=("", 12, "bold")).pack(side="left")
        ttk.Button(top, text="重新整理（重讀狀態）", command=self.refresh).pack(side="right")
        ttk.Button(top, text="檢查（verify）", command=self.do_verify).pack(side="right", padx=4)

        body = ttk.Frame(r)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, highlightthickness=0)
        vsb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas, padding=8)
        self.inner.bind("<Configure>", lambda e: (canvas.configure(scrollregion=canvas.bbox("all")), self._fit_notes()))
        self.win = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        # 內容區寬度跟著視窗，長文字才會在視窗內換行而不是被截掉；版面變動後重算每個說明文字的換行寬
        self.notes: list = []
        canvas.bind("<Configure>", lambda e: (canvas.itemconfigure(self.win, width=e.width), self._fit_notes()))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.canvas = canvas

        def wheel(e):  # 只在滑鼠位於上方設定區時捲動；在底下的紀錄區滾輪不影響上面
            w = e.widget
            while w is not None:
                if w is self.canvas or w is self.inner:
                    self.canvas.yview_scroll(-int(e.delta / 120), "units")
                    return
                w = getattr(w, "master", None)
        r.bind_all("<MouseWheel>", wheel)

        bottom = ttk.Frame(r, padding=8)
        bottom.pack(fill="x")
        self.diff_var = tk.StringVar(value="將變更：無")
        ttk.Label(bottom, textvariable=self.diff_var, wraplength=940, justify="left").pack(fill="x")
        btns = ttk.Frame(bottom)
        btns.pack(fill="x", pady=4)
        self.apply_btn = ttk.Button(btns, text="套用", command=self.do_apply)
        self.apply_btn.pack(side="left")
        ttk.Button(btns, text="取消（恢復成目前狀態）", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(btns, text="全部啟用", command=lambda: self.set_preset(True)).pack(side="left", padx=4)
        ttk.Button(btns, text="全部關閉", command=lambda: self.set_preset(False)).pack(side="left", padx=4)
        ttk.Button(btns, text="匯出設定", command=self.do_export).pack(side="left", padx=4)
        ttk.Button(btns, text="匯入設定", command=self.do_import).pack(side="left", padx=4)
        ttk.Button(btns, text="備份／還原", command=self.do_backups).pack(side="left", padx=4)
        ttk.Button(btns, text="解除安裝", command=self.do_uninstall).pack(side="right")
        self.log = tk.Text(bottom, height=9, wrap="word", state="disabled", font=("Consolas", 10))
        self.log.pack(fill="x")
        self.log.bind("<MouseWheel>", lambda e: (self.log.yview_scroll(-int(e.delta / 120), "units"), "break")[1])

    def _section(self, title: str) -> ttk.LabelFrame:
        f = ttk.LabelFrame(self.inner, text=title, padding=8)
        f.pack(fill="x", pady=4)
        return f

    def _no_wheel_change(self, w):
        """下拉選單與數字框：滾輪只捲頁面，不改值（使用者回饋：滾輪會不小心改設定）。"""
        w.bind("<MouseWheel>", lambda e: (self.canvas.yview_scroll(-int(e.delta / 120), "units"), "break")[1])
        return w

    def _note(self, parent, text, wrap=420, **grid):
        """說明文字：先給一個估計寬度，版面算好後由 _fit_notes() 依實際剩餘寬度重設換行寬，確保不被截掉。"""
        lb = ttk.Label(parent, text=text, foreground="#555", wraplength=wrap, justify="left")
        lb.grid(**grid)
        self.notes.append(lb)
        return lb

    def _fit_notes(self, _e=None):
        if getattr(self, "_fit_job", None):
            self.root.after_cancel(self._fit_job)
        self._fit_job = self.root.after(60, self._fit_notes_now)

    def _fit_notes_now(self):
        self._fit_job = None
        try:
            self.root.update_idletasks()  # 先讓版面定位，rootx 才準
            right = self.inner.winfo_rootx() + self.inner.winfo_width() - 24
            for lb in self.notes:
                if not lb.winfo_exists():
                    continue
                avail = right - lb.winfo_rootx()
                if avail > 0 and abs(int(lb.cget("wraplength")) - avail) > 8:
                    lb.configure(wraplength=max(140, avail))
        except tk.TclError:
            pass

    def _rebuild(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.notes = []
        s, f = self.state, self.form
        self.key_vars.clear(); self.key_dirty.clear(); self.key_status.clear(); self.mode_vars.clear(); self.mode_boxes.clear(); self.server_vars.clear(); self.env_vars.clear()
        self.title_var.set(f"repo v{s['repo_version']}　已安裝：{('v' + s['version']) if s['installed'] else '尚未安裝'}　設定目錄：{self.lay.home}")

        # 環境
        env = self._section("環境（每次開啟實際偵測）")
        for i, (k, it) in enumerate(s["env"].items()):
            ttk.Label(env, text=f"{MARK[it.ok]} {it.detail}", wraplength=1000, justify="left").grid(row=i, column=0, sticky="w")
            if it.action in ("ffmpeg", "pwsh7", "faster_whisper"):
                txt = {"ffmpeg": "安裝 ffmpeg（winget）", "pwsh7": "安裝 PowerShell 7（MSI，會跳 UAC）", "faster_whisper": "安裝 faster-whisper（pip）"}[it.action]
                ttk.Button(env, text=txt, command=lambda a=it.action: self.do_install(a)).grid(row=i, column=1, sticky="e", padx=4)
            elif it.action in gm.DOWNLOAD_PAGES:
                ttk.Button(env, text="開下載頁", command=lambda a=it.action: webbrowser.open(gm.DOWNLOAD_PAGES[a])).grid(row=i, column=1, sticky="e", padx=4)
        env.columnconfigure(0, weight=1)

        # 核心
        core = self._section("核心（規則、skill）——安裝後永遠啟用")
        ttk.Label(core, text=f"{MARK[s['installed']]} {'已安裝' if s['installed'] else '尚未安裝（按套用會安裝）'}").pack(anchor="w")
        self.guard_var = tk.BooleanVar(value=f.usage_guard)
        ttk.Checkbutton(core, text=f"用量守門 hook（到門檻才提示收尾，沒到完全不動；目前 settings.json：{'已註冊' if s['hooks']['usage_guard'] else '未註冊'}）",
                        variable=self.guard_var, command=self.update_diff).pack(anchor="w")
        th = ttk.Frame(core); th.pack(anchor="w", pady=4)
        ttk.Label(th, text="門檻：5 小時 ≥").pack(side="left")
        self.five_var = tk.StringVar(value=str(f.thresholds["fiveHour"]))
        self.seven_var = tk.StringVar(value=str(f.thresholds["sevenDay"]))
        self._no_wheel_change(ttk.Spinbox(th, from_=1, to=100, width=5, textvariable=self.five_var, command=self.update_diff)).pack(side="left")
        ttk.Label(th, text="%　7 天 ≥").pack(side="left")
        self._no_wheel_change(ttk.Spinbox(th, from_=1, to=100, width=5, textvariable=self.seven_var, command=self.update_diff)).pack(side="left")
        ttk.Label(th, text="%").pack(side="left")
        for v in (self.five_var, self.seven_var):
            v.trace_add("write", lambda *a: self.update_diff())

        # 聯網
        webf = self._section("聯網來源（免金鑰搜尋／文件 MCP ＋ WebSearch 上限）")
        self.web_var = tk.BooleanVar(value=f.web_enabled)
        ttk.Checkbutton(webf, text="啟用聯網來源", variable=self.web_var, command=self.update_diff).grid(row=0, column=0, columnspan=4, sticky="w")
        row = 1
        for n, sv in s["web"]["servers"].items():
            var = tk.BooleanVar(value=f.servers.get(n, sv["wanted"]))
            self.server_vars[n] = var
            st = "已註冊" if sv["registered"] else "未註冊"
            if sv["key_registered"]:
                st += "＋金鑰版"
            elif not sv["keyable"]:
                st += "（純免費服務，沒有金鑰機制）"
            elif sv["registered"]:
                st += "（免金鑰版；填金鑰後會多註冊金鑰版）"
            ttk.Checkbutton(webf, text=n, variable=var, command=self.update_diff).grid(row=row, column=0, sticky="w")
            self._note(webf, f"{st}　工具：{', '.join(sv['tools'])}", wrap=600, row=row, column=1, columnspan=2, sticky="w", padx=8)
            row += 1
        for k, dv in s["web"]["env_defaults"].items():
            var = tk.StringVar(value=f.env.get(k, dv))
            self.env_vars[k] = var
            var.trace_add("write", lambda *a: self.update_diff())
            ttk.Label(webf, text=k).grid(row=row, column=0, sticky="w", pady=(6, 0))
            ent = ttk.Entry(webf, textvariable=var, width=12)
            ent.grid(row=row, column=1, sticky="w", padx=8, pady=(6, 0))
            if k in gm.ENV_READONLY:  # 編碼設定固定值，只顯示不可改（使用者回饋：不知道該填什麼）
                ent.state(["readonly"])
                desc = f"{gm.ENV_DESC.get(k, '')}；固定值，不可改；目前 settings.json：{s['web']['env'].get(k) or '未寫入'}"
            else:
                desc = f"{gm.ENV_DESC.get(k, '')}；預設 {dv}；目前 settings.json：{s['web']['env'].get(k) or '未寫入'}"
            self._note(webf, desc, wrap=900, row=row + 1, column=0, columnspan=3, sticky="w", padx=(24, 0))
            row += 2
        webf.columnconfigure(2, weight=1)

        # 影片
        vf = self._section("影片來源（YouTube／網路影片／本機 mp4：搜尋、逐字稿、截圖、直播、下載）")
        self.video_var = tk.BooleanVar(value=f.video_enabled)
        ttk.Checkbutton(vf, text="啟用影片來源（pip 裝 yt-dlp、youtube-transcript-api）", variable=self.video_var, command=self.update_diff).grid(row=0, column=0, sticky="w")
        pk = s["video"]["packages"]
        self._note(vf, "套件：" + "、".join(f"{m} {MARK[v is not None]}" for m, v in pk.items()), wrap=500, row=0, column=1, sticky="w", padx=8)
        ttk.Label(vf, text="下載資料夾（使用者說要存檔時；空白＝~/Downloads）").grid(row=1, column=0, sticky="w")
        self.dl_var = tk.StringVar(value=f.download_dir)
        self.dl_var.trace_add("write", lambda *a: self.update_diff())
        ttk.Entry(vf, textvariable=self.dl_var, width=40).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Button(vf, text="瀏覽…", command=self.pick_dir).grid(row=1, column=2, sticky="w")

        # 金鑰
        kf = self._section("金鑰（存本機 local.json，不進 repo；框內是目前的值，改了才會更新；搜尋類預設「免費優先」）")
        hdr = ("", 9, "bold")
        ttk.Label(kf, text="名稱", font=hdr).grid(row=0, column=0, sticky="w")
        ttk.Label(kf, text="狀態", font=hdr).grid(row=0, column=1, sticky="w")
        ttk.Label(kf, text="金鑰值（按「顯示」看明文）", font=hdr).grid(row=0, column=2, sticky="w")
        ttk.Label(kf, text="模式", font=hdr).grid(row=0, column=5, sticky="w")
        self.key_orig: dict[str, str] = {}
        for i, (n, k) in enumerate(s["keys"].items(), start=1):
            ttk.Label(kf, text=f"{k['label']}（{n}）").grid(row=i, column=0, sticky="w")
            self.key_status[n] = tk.StringVar(value="已設定" if k["present"] else "未設定")
            ttk.Label(kf, textvariable=self.key_status[n], width=18).grid(row=i, column=1, sticky="w")
            var = tk.StringVar(value=k["value"])
            self.key_vars[n] = var
            self.key_orig[n] = k["value"]
            self.key_dirty[n] = False
            ent = ttk.Entry(kf, textvariable=var, width=34, show="•")
            ent.grid(row=i, column=2, sticky="w", padx=4)
            var.trace_add("write", lambda *a, n=n: self._key_typed(n))
            ttk.Button(kf, text="顯示", width=5, command=lambda e=ent: e.configure(show="" if e.cget("show") else "•")).grid(row=i, column=3)
            bf = ttk.Frame(kf); bf.grid(row=i, column=4, padx=4)
            ttk.Button(bf, text="測試", width=5, command=lambda n=n: self.do_test_key(n)).pack(side="left")
            ttk.Button(bf, text="清除", width=5, command=lambda n=n: self._key_clear(n)).pack(side="left", padx=2)
            if k["mode"]:
                mv = tk.StringVar(value="免費優先" if (f.key_modes.get(n, k["mode"]) == "fallback" or not k["present"]) else "一律用金鑰")
                self.mode_vars[n] = mv
                cb = self._no_wheel_change(ttk.Combobox(kf, textvariable=mv, values=["免費優先", "一律用金鑰"], width=10, state="readonly"))
                cb.grid(row=i, column=5, sticky="w")
                cb.bind("<<ComboboxSelected>>", lambda e: self.update_diff())
                self.mode_boxes[n] = cb
                if not k["present"]:  # 沒金鑰就沒有「一律用金鑰」可選
                    cb.state(["disabled"])
            else:
                ttk.Label(kf, text="只能用金鑰", foreground="#555").grid(row=i, column=5, sticky="w")
            ttk.Button(kf, text="註冊網頁", width=8, command=lambda u=k["url"]: webbrowser.open(u)).grid(row=i, column=6, padx=4)
            self._note(kf, k["note"], wrap=300, row=i, column=7, sticky="w", padx=6)
        kf.columnconfigure(7, weight=1)
        ttk.Label(kf, text="「只能用金鑰」＝此服務沒有免金鑰版；「免費優先」＝免金鑰版與金鑰版並存、撞限流才用金鑰（沒填金鑰時不可選）；「註冊網頁」開官方申請頁，金鑰免費", foreground="#555").grid(row=len(s["keys"]) + 1, column=0, columnspan=8, sticky="w", pady=(6, 0))

        # Chrome
        cf = self._section("Claude in Chrome（開網頁看、操作需登入網站、教操作前核對畫面）")
        c = s["chrome"]
        ttk.Label(cf, text=f"① 擴充功能已安裝：{MARK[c['extension']]}　② 已和 Claude Code 登記（native host）：{MARK[c['native_host']]}　"
                           f"③ 實際連線：按右邊按鈕測（約一場對話開場的用量，不自動跑）", wraplength=900, justify="left").grid(row=0, column=0, sticky="w")
        cf.columnconfigure(0, weight=1)
        ttk.Button(cf, text="③ 實際連線測試", command=self.do_chrome_test).grid(row=0, column=1, padx=6)
        self.chrome_var = tk.BooleanVar(value=bool(c["default_enabled"]))
        cb = ttk.Checkbutton(cf, text="Enabled by default（每場對話自動連 Chrome；寫 ~/.claude.json，會先備份）", variable=self.chrome_var, command=self.update_diff)
        cb.grid(row=1, column=0, sticky="w")
        if c["default_enabled"] is None:
            cb.state(["disabled"])
            ttk.Label(cf, text="（找不到 ~/.claude.json：先開過一次 Claude Code 再回來）", foreground="#555").grid(row=1, column=1, sticky="w")
        ttk.Label(cf, text="沒裝擴充：Chrome 線上商店搜「Claude in Chrome」，同一帳號登入。", foreground="#555").grid(row=2, column=0, sticky="w")

        self.update_diff()
        self._fit_notes()

    # ---------- 表單 ↔ 畫面 ----------
    def _collect(self) -> gm.Form:
        f = gm.form_from_state(self.state)
        f.web_enabled = self.web_var.get()
        f.servers = {n: v.get() for n, v in self.server_vars.items()}
        f.env = {k: v.get().strip() for k, v in self.env_vars.items()}
        f.video_enabled = self.video_var.get()
        f.usage_guard = self.guard_var.get()
        f.download_dir = self.dl_var.get().strip()
        for n, v in self.key_vars.items():
            if v.get().strip() != self.key_orig.get(n, ""):
                f.keys[n] = v.get().strip()
        for n, mv in self.mode_vars.items():
            has_key = bool(self.key_vars[n].get().strip())
            f.key_modes[n] = "always" if (mv.get() == "一律用金鑰" and has_key) else "fallback"
        try:
            f.thresholds = {"fiveHour": float(self.five_var.get()), "sevenDay": float(self.seven_var.get())}
        except ValueError:
            f.thresholds = dict(self.state["thresholds"])
        if self.state["chrome"]["default_enabled"] is not None:
            f.chrome_default_enabled = self.chrome_var.get()
        return f

    def _key_typed(self, n):
        cur = self.key_vars[n].get().strip()
        orig = self.key_orig.get(n, "")
        self.key_dirty[n] = cur != orig
        cb = self.mode_boxes.get(n)
        if cb is not None:  # 有值才能選模式；清空就鎖回免費優先
            if cur:
                cb.state(["!disabled"])
            else:
                self.mode_vars[n].set("免費優先")
                cb.state(["disabled"])
        if cur == orig:
            self.key_status[n].set("已設定" if orig else "未設定")
        else:
            self.key_status[n].set("將更新" if cur else ("將清除" if orig else "未設定"))
        self.update_diff()

    def _key_clear(self, n):
        self.key_vars[n].set("")
        self._key_typed(n)

    def update_diff(self):
        try:
            ch = gm.diff(self.state, self._collect())
        except Exception as e:  # noqa: BLE001
            self.diff_var.set(f"將變更：（表單有誤：{e}）")
            return
        self.diff_var.set("將變更：無（按套用不會動任何東西）" if not ch else f"將變更 {len(ch)} 項：" + "；".join(c.text for c in ch))

    def set_preset(self, on: bool):
        f = gm.preset(self._collect(), self.state, on)
        self.web_var.set(f.web_enabled)
        for n, v in self.server_vars.items():
            v.set(f.servers.get(n, False))
        self.video_var.set(f.video_enabled)
        self.guard_var.set(f.usage_guard)
        if self.state["chrome"]["default_enabled"] is not None and f.chrome_default_enabled is not None:
            self.chrome_var.set(f.chrome_default_enabled)
        self.update_diff()

    def pick_dir(self):
        d = filedialog.askdirectory(title="下載資料夾")
        if d:
            self.dl_var.set(d)

    # ---------- 背景工作 ----------
    def _log(self, line: str):
        self.q.put(("log", line))

    def _pump(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", payload + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "done":
                    self.busy = False
                    self.apply_btn.configure(state="normal")
                    if payload:
                        self.refresh()
                    if getattr(self, "_close_after_apply", False):
                        self._close_after_apply = False
                        self.root.destroy()
                        return
                elif kind == "keystatus":
                    n, text = payload
                    self.key_status[n].set(text)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _run_bg(self, fn, refresh_after=True):
        if self.busy:
            messagebox.showinfo("稍等", "有工作正在執行")
            return
        self.busy = True
        self.apply_btn.configure(state="disabled")

        def work():
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                self._log(f"❌ 例外：{type(e).__name__}: {e}")
            finally:
                self.q.put(("done", refresh_after))
        threading.Thread(target=work, daemon=True).start()

    # ---------- 動作 ----------
    def refresh(self):
        try:
            self.state = gm.read_state(self.lay, repo=REPO)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("讀取狀態失敗", str(e))
            return
        self.form = gm.form_from_state(self.state)
        self._rebuild()

    def do_apply(self):
        form = self._collect()
        ch = gm.diff(self.state, form)
        if not ch:
            messagebox.showinfo("套用", "沒有變更。")
            return
        if not getattr(self, "_close_after_apply", False) and not messagebox.askyesno("套用", "將執行：\n\n" + "\n".join("• " + c.text for c in ch) + "\n\n確定？"):
            return
        state = self.state

        def job():
            self._log("=== 套用開始 ===")
            code = gm.apply_form(self.lay, PY, state, form, self._log, repo=REPO)
            self._log(f"=== 套用{'完成' if code == 0 else '完成但有項目失敗（見 ❌）'}；重開 Claude Code 對話後生效 ===")
        self._run_bg(job)

    def do_verify(self):
        def job():
            self._log("=== verify ===")
            code, lines = commands.verify(self.lay, repo=REPO)
            for ln in lines:
                self._log(web.mask(ln, gm._local(self.lay)))
        self._run_bg(job, refresh_after=False)

    def do_install(self, action: str):
        gpu = False
        if action == "faster_whisper":
            gpu = messagebox.askyesno("faster-whisper", "這台有 NVIDIA 顯卡嗎？\n是：一併裝 CUDA 套件（約 1.5GB，GPU 辨識快 8 倍）\n否：純 CPU")
        if action == "pwsh7" and not messagebox.askyesno("PowerShell 7", "會用 winget 安裝 MSI 版並跳出 UAC，安裝後請重開 Claude Code。繼續？"):
            return

        def job():
            self._log(f"=== 安裝 {action} ===")
            code, out = gm.install_action(action, PY, gpu=gpu)
            self._log(out.strip()[-1200:] or "(無輸出)")
            self._log(f"{'✅' if code == 0 else '❌'} 結束碼 {code}")
        self._run_bg(job)

    def do_test_key(self, n: str):
        keys = {m: v.get().strip() for m, v in self.key_vars.items() if v.get().strip()}  # 框內的值（含尚未套用的）
        val = keys.get(n, "")
        if not val:
            messagebox.showinfo("測試", "請先輸入金鑰")
            return
        self.q.put(("keystatus", (n, "測試中…")))

        def job():
            ok, msg = gm.test_key(n, val, keys)
            self.q.put(("keystatus", (n, f"{'✅ 有效' if ok else '❌ 無效'} {msg}")))
            self._log(f"金鑰 {n} 測試：{'✅' if ok else '❌'} {msg}")
        self._run_bg(job, refresh_after=False)

    def do_chrome_test(self):
        if not messagebox.askyesno("Chrome 實際連線測試", "會在背景跑一次 Claude Code（--chrome），約 40 秒，並用掉約一場對話開場的用量。繼續？"):
            return

        def job():
            self._log("=== Chrome 實際連線測試（claude -p --chrome）===")
            ok, msg = gm.chrome_live_test()
            self._log(f"{'✅ 可用' if ok else '❌ 不可用'}：{msg}")
        self._run_bg(job, refresh_after=False)

    def do_export(self):
        p = filedialog.asksaveasfilename(title="匯出設定（不含金鑰）", defaultextension=".json", initialfile="claude-dev-system-profile.json")
        if not p:
            return
        Path(p).write_text(json.dumps(gm.export_profile(self.state, self._collect()), ensure_ascii=False, indent=2), encoding="utf-8")
        self._log(f"已匯出 {p}")

    def do_import(self):
        p = filedialog.askopenfilename(title="匯入設定", filetypes=[("JSON", "*.json")])
        if not p:
            return
        try:
            f = gm.import_profile(self._collect(), json.loads(Path(p).read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("匯入失敗", str(e))
            return
        self.web_var.set(f.web_enabled)
        for n, v in self.server_vars.items():
            v.set(f.servers.get(n, v.get()))
        for k, v in self.env_vars.items():
            v.set(f.env.get(k, v.get()))
        self.video_var.set(f.video_enabled)
        self.guard_var.set(f.usage_guard)
        self.dl_var.set(f.download_dir or "")
        self.five_var.set(str(f.thresholds.get("fiveHour", self.five_var.get())))
        self.seven_var.set(str(f.thresholds.get("sevenDay", self.seven_var.get())))
        for n, mv in self.mode_vars.items():
            mv.set("一律用金鑰" if f.key_modes.get(n) == "always" else "免費優先")
        if f.chrome_default_enabled is not None and self.state["chrome"]["default_enabled"] is not None:
            self.chrome_var.set(f.chrome_default_enabled)
        self._log(f"已匯入 {p}（金鑰不在設定檔內，請另外填）")
        self.update_diff()

    def do_backups(self):
        items = gm.list_backups(self.lay)
        if not items:
            messagebox.showinfo("備份", "沒有 settings.json 備份")
            return
        w = tk.Toplevel(self.root)
        w.title("settings.json 備份")
        lb = tk.Listbox(w, width=90, height=12)
        lb.pack(padx=8, pady=8)
        for at, p in items:
            lb.insert("end", f"{at}　{p}")

        def restore():
            i = lb.curselection()
            if not i:
                return
            at, p = items[i[0]]
            if messagebox.askyesno("還原", f"用 {at} 的備份覆蓋現在的 settings.json？"):
                gm.restore_backup(self.lay, p)
                self._log(f"已還原 settings.json ← {p}")
                w.destroy()
                self.refresh()
        ttk.Button(w, text="還原選取的備份", command=restore).pack(pady=4)

    def do_uninstall(self):
        if not messagebox.askyesno("解除安裝", "只移除這套工具加進去的東西：\n• settings.json 的兩條 hook 與 env\n• CLAUDE.md 的標記區塊\n• 它註冊的 MCP\n• 規則／工具檔與 4 個 skill\n\n"
                                            "不會移除：pip 裝的 yt-dlp／faster-whisper、ffmpeg、PowerShell 7、Chrome 擴充、Python、Claude Code、金鑰檔 local.json、這個設定程式本身。\n\n確定？"):
            return

        def job():
            self._log("=== 解除安裝 ===")
            code, lines = commands.uninstall(self.lay)
            for ln in lines:
                self._log(web.mask(ln, gm._local(self.lay)))
        self._run_bg(job)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="claude-dev-system 設定視窗")
    ap.add_argument("--claude-home")
    a = ap.parse_args(argv)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", max(1.0, root.winfo_fpixels("1i") / 72.0))
    except Exception:  # noqa: BLE001
        pass
    App(root, Layout(claude_home(a.claude_home)))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
