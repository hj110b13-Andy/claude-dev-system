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

from cds import appdir, commands, gui_model as gm, selftest, web  # noqa: E402
from cds.paths import FROZEN, REPO, Layout, claude_home, repo_version  # noqa: E402

MARK = {True: "✅", False: "❌", None: "⚠️"}
MODE_LABEL = {"fallback": "免費優先", "always": "一律用金鑰", "free": "只用免金鑰"}  # local.json keyMode ↔ 視窗文字
MODE_VALUE = {v: k for k, v in MODE_LABEL.items()}


def base_font_name() -> str:
    return "Microsoft JhengHei UI" if sys.platform == "win32" else ""
PY = gm.find_system_python()[0] if FROZEN else Path(sys.executable).as_posix()  # exe 模式：hook 與 pip 要用系統 Python，不是 exe


class App:
    def __init__(self, root: tk.Tk, lay: Layout):
        self.root, self.lay = root, lay
        self.repo = appdir.effective_repo(lay)  # exe 模式：app/ 比內建新就用 app/
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
        for cls in (".", "TLabel", "TButton", "TCheckbutton", "TEntry", "TCombobox", "TSpinbox"):
            st.configure(cls, font=base_font)
        st.configure("TLabelframe.Label", font=(base_font[0], 12, "bold"), foreground="#1f4e79")
        self._build()
        self.refresh()
        root.protocol("WM_DELETE_WINDOW", self.on_close)  # 有未套用的變更時關閉要先問
        root.after(100, self._pump)
        root.after(1500, self._auto_check_update)  # 開窗後安靜檢查一次 GitHub 版本；有新版才問，連不上只記一行

    def on_close(self):
        if self.busy:  # 套用是多步驟（local.json → install → 門檻），中途砍掉會留半套狀態：做完才能關
            messagebox.showinfo("關閉", "有工作正在執行（套用／安裝／測試），請等它跑完再關閉。")
            return
        try:
            ch = gm.diff(self.state, self._collect())
        except Exception as e:  # noqa: BLE001
            if not messagebox.askyesno("關閉", f"表單有誤（{e}），無法判斷是否有未套用的變更。要放棄並關閉嗎？"):
                return
            ch = []
        if ch:
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
        ttk.Button(top, text="自我測試（9 題無頭對話，約 30 分鐘）", command=self.do_selftest).pack(side="right", padx=4)
        ttk.Button(top, text="檢查更新", command=self.do_check_update).pack(side="right", padx=4)

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
        # 「將變更」區：淡黃底＋邊框和上面的設定區分開；標題一行，每項變更各一行（使用者回饋：擠在一行太亂）
        dbox = tk.Frame(bottom, bg="#fff6d6", highlightbackground="#e0b400", highlightthickness=2, padx=8, pady=6)
        dbox.pack(fill="x", pady=(0, 4))
        self.diff_var = tk.StringVar(value="將變更：無")
        tk.Label(dbox, textvariable=self.diff_var, bg="#fff6d6", fg="#7a5200", font=(base_font_name(), 11, "bold"), anchor="w", justify="left").pack(fill="x")
        self.diff_text = tk.Text(dbox, height=1, wrap="word", bg="#fff6d6", fg="#333", relief="flat", font=(base_font_name(), 11), state="disabled", cursor="arrow")
        self.diff_text.pack(fill="x")
        self.diff_text.bind("<MouseWheel>", lambda e: (self.diff_text.yview_scroll(-int(e.delta / 120), "units"), "break")[1])
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
        self.log = tk.Text(bottom, height=7, wrap="word", state="disabled", font=("Consolas", 10))
        self.log.pack(fill="x")
        self.log.bind("<MouseWheel>", lambda e: (self.log.yview_scroll(-int(e.delta / 120), "units"), "break")[1])

    def _section(self, title: str) -> ttk.LabelFrame:
        """每一區：上方一條分隔線、粗體大標、區內留白加大，讓各區看起來不是擠成一坨（使用者回饋）。"""
        ttk.Separator(self.inner, orient="horizontal").pack(fill="x", pady=(14, 0))
        f = ttk.LabelFrame(self.inner, text=f"  {title}  ", padding=(14, 10, 14, 12))
        f.pack(fill="x", pady=(6, 4))
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
            right = self.inner.winfo_rootx() + self.inner.winfo_width() - 56  # 留出捲軸與邊框，字不貼邊
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
        src = "執行檔內建" if (FROZEN and self.repo == REPO) else ("已下載的 app/" if self.repo != REPO else "原始碼 repo")
        warn = "　⚠️ 來源比已安裝舊，按「檢查更新」再套用" if gm.source_older(s) else ""
        self.title_var.set(f"來源 v{s['repo_version']}（{src}）　已安裝：{('v' + s['version']) if s['installed'] else '尚未安裝'}{warn}　設定目錄：{self.lay.home}")

        # 環境
        ev = list(s["env"].values())
        env = self._section(f"環境（每次開啟實際偵測）　共 {len(ev)} 項：✅ {sum(1 for x in ev if x.ok is True)}　⚠️ {sum(1 for x in ev if x.ok is None)}　❌ {sum(1 for x in ev if x.ok is False)}")
        for i, (k, it) in enumerate(s["env"].items()):
            lb = ttk.Label(env, text=f"{MARK[it.ok]} {it.detail}", wraplength=1000, justify="left")
            lb.grid(row=i, column=0, sticky="w")
            self.notes.append(lb)  # 讓換行寬跟著視窗（ffmpeg 長路徑原本在寬螢幕也提早斷行）
            if it.action in ("ffmpeg", "pwsh7", "faster_whisper"):
                txt = {"ffmpeg": "安裝 ffmpeg（winget）", "pwsh7": "安裝 PowerShell 7（MSI，會跳 UAC）", "faster_whisper": "安裝 faster-whisper（pip）"}[it.action]
                ttk.Button(env, text=txt, command=lambda a=it.action: self.do_install(a)).grid(row=i, column=1, sticky="e", padx=4)
            elif it.action in gm.DOWNLOAD_PAGES:
                ttk.Button(env, text="開下載頁", command=lambda a=it.action: webbrowser.open(gm.DOWNLOAD_PAGES[a])).grid(row=i, column=1, sticky="e", padx=4)
        env.columnconfigure(0, weight=1)

        # 核心
        core = self._section("核心（規則、skill）——安裝後永遠啟用　共 3 項設定：用量守門、門檻、背景任務巡檢")
        ttk.Label(core, text=f"{MARK[s['installed']]} {'已安裝' if s['installed'] else '尚未安裝（按套用會安裝）'}").pack(anchor="w")
        self.notes.append(ttk.Label(core, text=gm.TOOL_DESC["core"], foreground="#555", wraplength=900, justify="left")); self.notes[-1].pack(anchor="w")
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
        ttk.Label(th, text="%　（這是全域值；專案若有自己的 .claude/dispatch-config.json，該專案以它為準）", foreground="#555").pack(side="left")
        for v in (self.five_var, self.seven_var):
            v.trace_add("write", lambda *a: self.update_diff())
        tc = f.task_check
        tcf = ttk.Frame(core); tcf.pack(anchor="w", pady=4)
        self.tc_var = tk.BooleanVar(value=bool(tc.get("enabled")))
        ttk.Checkbutton(tcf, text="背景任務巡檢：有背景任務或 agent 在跑時，每", variable=self.tc_var, command=self.update_diff).pack(side="left")
        self.tc_min_var = tk.StringVar(value=str(int(tc.get("minutes", gm.DEFAULT_TASK_CHECK["minutes"]))))
        self._no_wheel_change(ttk.Spinbox(tcf, from_=1, to=120, width=5, textvariable=self.tc_min_var, command=self.update_diff)).pack(side="left")
        ttk.Label(tcf, text="分鐘自動檢查一次所有任務（結束或出錯就處理；全部結束就停；沒有任務時不會跑）").pack(side="left")
        self.tc_min_var.trace_add("write", lambda *a: self.update_diff())
        uf = ttk.Frame(core); uf.pack(anchor="w", fill="x", pady=(6, 0))
        self.usage_var = tk.StringVar(value=s.get("usage", {}).get("text", ""))
        self.notes.append(ttk.Label(uf, textvariable=self.usage_var, wraplength=800, justify="left")); self.notes[-1].pack(side="left")
        ttk.Button(uf, text="重新讀取用量", command=self.do_usage).pack(side="left", padx=8)

        # 聯網
        srv = s["web"]["servers"]
        webf = self._section(f"聯網來源（免金鑰搜尋／文件 MCP ＋ WebSearch 上限）　共 {len(srv)} 個 MCP：目前開啟 {sum(1 for x in srv.values() if x['wanted'])}、已註冊 {sum(1 for x in srv.values() if x['registered'])}；環境變數 {len(s['web']['env_defaults'])} 個")
        self.web_var = tk.BooleanVar(value=f.web_enabled)
        ttk.Checkbutton(webf, text="啟用聯網來源", variable=self.web_var, command=self.update_diff).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        row = 1
        for n, sv in s["web"]["servers"].items():  # 每個 MCP 兩列：名稱＋功能、狀態＋工具（原本塞一行會被擠到最右邊、工具名從中間斷行）
            var = tk.BooleanVar(value=f.servers.get(n, sv["wanted"]))
            self.server_vars[n] = var
            st = "已註冊" if sv["registered"] else "未註冊"
            if sv["key_registered"]:
                st += "＋金鑰版"
            elif not sv["keyable"]:
                st += "（純免費服務，沒有金鑰機制）"
            elif sv["registered"]:
                st += "（免金鑰版；填金鑰後會多註冊金鑰版）"
            ttk.Checkbutton(webf, text=n, variable=var, command=self.update_diff, width=12).grid(row=row, column=0, sticky="nw")
            self._note(webf, gm.MCP_DESC.get(n, ""), wrap=900, row=row, column=1, sticky="w", padx=8)
            self._note(webf, f"狀態：{st}　　工具：{', '.join(sv['tools'])}", wrap=900, row=row + 1, column=1, sticky="w", padx=8, pady=(0, 8))
            row += 2
        ef = ttk.Frame(webf)  # env 列自己一個格線，長變數名不會把上面 MCP 的欄位撐開
        ef.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(ef, text="環境變數（寫進 settings.json 的 env）", font=("", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        erow = 1
        for k, dv in s["web"]["env_defaults"].items():
            var = tk.StringVar(value=f.env.get(k, dv))
            self.env_vars[k] = var
            var.trace_add("write", lambda *a: self.update_diff())
            ttk.Label(ef, text=k).grid(row=erow, column=0, sticky="w")
            ent = ttk.Entry(ef, textvariable=var, width=12)
            ent.grid(row=erow, column=1, sticky="w", padx=8)
            if k in gm.ENV_READONLY:  # 編碼設定固定值，只顯示不可改（使用者回饋：不知道該填什麼）
                ent.state(["readonly"])
                desc = f"{gm.ENV_DESC.get(k, '')}；固定值，不可改；目前 settings.json：{s['web']['env'].get(k) or '未寫入'}"
            else:
                desc = f"{gm.ENV_DESC.get(k, '')}；預設 {dv}；目前 settings.json：{s['web']['env'].get(k) or '未寫入'}"
            self._note(ef, desc, wrap=900, row=erow + 1, column=0, columnspan=2, sticky="w", padx=(24, 0), pady=(0, 6))
            erow += 2
        webf.columnconfigure(1, weight=1)

        # 影片
        pk0 = s["video"]["packages"]
        vf = self._section(f"影片來源（YouTube／網路影片／本機 mp4）　套件 {sum(1 for v in pk0.values() if v is not None)}/{len(pk0)} 已裝")
        self.notes.append(ttk.Label(vf, text=gm.TOOL_DESC["video"], foreground="#555", wraplength=900, justify="left")); self.notes[-1].grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
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
        kf = self._section(f"金鑰（存本機 local.json，不進 repo；框內是目前的值，改了才會更新；搜尋類預設「免費優先」）　共 {len(s['keys'])} 把：已設定 {sum(1 for k in s['keys'].values() if k['present'])}、未設定 {sum(1 for k in s['keys'].values() if not k['present'])}")
        hdr = ("", 9, "bold")
        ttk.Label(kf, text="名稱", font=hdr).grid(row=0, column=0, sticky="w")
        ttk.Label(kf, text="狀態", font=hdr).grid(row=0, column=1, sticky="w")
        ttk.Label(kf, text="金鑰值（按「顯示」看明文）", font=hdr).grid(row=0, column=2, sticky="w")
        ttk.Label(kf, text="模式", font=hdr).grid(row=0, column=5, sticky="w")
        ttk.Label(kf, text="帳號備註（自己填：用哪個帳號申請的）", font=hdr).grid(row=0, column=7, sticky="w", padx=6)
        self.key_orig: dict[str, str] = {}
        self.note_vars: dict[str, tk.StringVar] = {}
        self.note_orig: dict[str, str] = {}
        for idx, (n, k) in enumerate(s["keys"].items()):
            i = 2 * idx + 1  # 每把金鑰兩列：第一列欄位，第二列整寬說明（右側窄欄會把說明擠成一個字一行）
            ttk.Label(kf, text=f"{k['label']}（{n}）").grid(row=i, column=0, sticky="w")
            self.key_status[n] = tk.StringVar(value="已設定" if k["present"] else "未設定")
            ttk.Label(kf, textvariable=self.key_status[n], width=18).grid(row=i, column=1, sticky="w")
            var = tk.StringVar(value=k["value"])
            self.key_vars[n] = var
            self.key_orig[n] = k["value"]
            self.key_dirty[n] = False
            ent = ttk.Entry(kf, textvariable=var, width=30, show="•")
            ent.grid(row=i, column=2, sticky="w", padx=4)
            var.trace_add("write", lambda *a, n=n: self._key_typed(n))
            ttk.Button(kf, text="顯示", width=5, command=lambda e=ent: e.configure(show="" if e.cget("show") else "•")).grid(row=i, column=3)
            bf = ttk.Frame(kf); bf.grid(row=i, column=4, padx=4)
            ttk.Button(bf, text="測試", width=5, command=lambda n=n: self.do_test_key(n)).pack(side="left")
            ttk.Button(bf, text="清除", width=5, command=lambda n=n: self._key_clear(n)).pack(side="left", padx=2)
            if k["mode"]:
                mv = tk.StringVar(value=MODE_LABEL.get(f.key_modes.get(n, k["mode"]), "免費優先") if k["present"] else "免費優先")
                self.mode_vars[n] = mv
                cb = self._no_wheel_change(ttk.Combobox(kf, textvariable=mv, values=list(MODE_LABEL.values()), width=11, state="readonly"))
                cb.grid(row=i, column=5, sticky="w")
                cb.bind("<<ComboboxSelected>>", lambda e: self.update_diff())
                self.mode_boxes[n] = cb
                if not k["present"]:  # 沒金鑰就沒有「一律用金鑰」可選
                    cb.state(["disabled"])
            else:
                ttk.Label(kf, text="只能用金鑰", foreground="#555").grid(row=i, column=5, sticky="w")
            ttk.Button(kf, text="註冊網頁", width=8, command=lambda u=k["url"]: webbrowser.open(u)).grid(row=i, column=6, padx=4)
            nv = tk.StringVar(value=k.get("account", ""))
            self.note_vars[n] = nv
            self.note_orig[n] = k.get("account", "")
            nv.trace_add("write", lambda *a: self.update_diff())
            ttk.Entry(kf, textvariable=nv, width=22).grid(row=i, column=7, sticky="w", padx=6)
            self._note(kf, k["note"], wrap=900, row=i + 1, column=0, columnspan=8, sticky="w", padx=(24, 0), pady=(0, 6))
        kf.columnconfigure(7, weight=1)
        ttk.Label(kf, text="「只能用金鑰」＝此服務沒有免金鑰版；「免費優先」＝免金鑰版與金鑰版並存、撞限流才用金鑰（沒填金鑰時不可選）；「只用免金鑰」＝金鑰留著不註冊；每多註冊一個金鑰版，每次工具呼叫約多讀 1,900 token 的伺服器說明（五個約 9,400，2026-11-01 實測）；「註冊網頁」開官方申請頁，金鑰免費；「測試」對 parallel／exa／tavily 會真的用掉 1 次搜尋額度", foreground="#555").grid(row=2 * len(s["keys"]) + 1, column=0, columnspan=8, sticky="w", pady=(6, 0))

        # Chrome
        c0 = s["chrome"]
        cf = self._section(f"Claude in Chrome（開網頁看、操作需登入網站、教操作前核對畫面）　共 3 項檢查：✅ {sum(1 for v in (c0['extension'], c0['native_host']) if v is True)} 已通過、1 項要手動按")
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
            f.key_modes[n] = MODE_VALUE.get(mv.get(), "fallback") if has_key else "fallback"
        for n, nv in self.note_vars.items():
            if nv.get().strip() != self.note_orig.get(n, ""):
                f.key_notes[n] = nv.get().strip()
        try:
            f.thresholds = {"fiveHour": float(self.five_var.get()), "sevenDay": float(self.seven_var.get())}
        except ValueError:
            f.thresholds = dict(self.state["thresholds"])
        try:
            f.task_check = {"enabled": self.tc_var.get(), "minutes": max(1, int(self.tc_min_var.get()))}
        except ValueError:
            f.task_check = dict(self.state.get("task_check") or gm.DEFAULT_TASK_CHECK)
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
            self.diff_text.configure(state="normal"); self.diff_text.delete("1.0", "end"); self.diff_text.configure(state="disabled", height=1)
            return
        self._set_diff(ch)

    def _set_diff(self, ch):
        self.diff_var.set("將變更：無（按套用不會動任何東西）" if not ch else f"將變更 共 {len(ch)} 項：")
        self.diff_text.configure(state="normal")
        self.diff_text.delete("1.0", "end")
        self.diff_text.insert("end", chr(10).join(f"{i}. {c.text}" for i, c in enumerate(ch, 1)))
        self.diff_text.configure(state="disabled", height=max(1, min(len(ch), 6)))  # 最多 6 行，再多就在框內捲（滾輪）

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
                elif kind == "usage":
                    self.usage_var.set(payload)
                elif kind == "ask_update":
                    self._ask_update(payload)
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
            self.state = gm.read_state(self.lay, repo=self.repo, python=PY if FROZEN else None, importer=gm.system_importer(PY) if FROZEN else gm.video.default_importer)
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
        if not PY:
            messagebox.showerror("套用", "找不到系統的 Python ≥3.10（hook 與影片工具要用它）。請先在「環境」區按「開下載頁」安裝 Python，裝好後重開本程式。")
            return
        if not getattr(self, "_close_after_apply", False) and not messagebox.askyesno("套用", "將執行：\n\n" + "\n".join("• " + c.text for c in ch) + "\n\n確定？"):
            return
        state = self.state

        def job():
            self._log("=== 套用開始 ===")
            code = gm.apply_form(self.lay, PY, state, form, self._log, repo=self.repo)
            self._log(f"=== 套用{'完成' if code == 0 else '完成但有項目失敗（見 ❌）'}；重開 Claude Code 對話後生效 ===")
        self._run_bg(job)

    def do_verify(self):
        def job():
            self._log("=== verify ===")
            code, lines = commands.verify(self.lay, repo=self.repo)
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
        if self.busy:
            messagebox.showinfo("稍等", "有工作正在執行")
            return
        self.q.put(("keystatus", (n, "測試中…")))

        def job():
            ok, msg = gm.test_key(n, val, keys)
            self.q.put(("keystatus", (n, f"{'✅ 有效' if ok else '❌ 無效'} {msg}")))
            acct = self.note_vars[n].get().strip() if n in self.note_vars else ""
            self._log(f"金鑰 {n}{'（帳號：' + acct + '）' if acct else '（帳號備註未填）'} 測試：{'✅' if ok else '❌'} {msg}")
        self._run_bg(job, refresh_after=False)

    def _auto_check_update(self):
        if self.busy:
            return

        def job():
            info = appdir.check_update(self.lay, REPO)
            if info["error"]:
                self._log(f"自動檢查更新：{info['error']}（可稍後按「檢查更新」）")
            elif info["newer"]:
                self._log(f"自動檢查更新：有新版 v{info['local']} → v{info['remote']}")
                self.q.put(("ask_update", info))
            else:
                self._log(f"自動檢查更新：已是最新 v{info['local']}")
        self._run_bg(job, refresh_after=False)

    def do_check_update(self):
        def job():
            self._log("=== 檢查更新（GitHub master 的 config/VERSION）===")
            info = appdir.check_update(self.lay, REPO)
            if info["error"]:
                self._log(f"❌ {info['error']}")
                return
            if not info["newer"]:
                self._log(f"✅ 已是最新：v{info['local']}（GitHub v{info['remote']}）")
                return
            self._log(f"有新版：v{info['local']} → v{info['remote']}")
            self.q.put(("ask_update", info))
        self._run_bg(job, refresh_after=False)

    def _ask_update(self, info):
        if not messagebox.askyesno("更新", f"GitHub 有新版 v{info['remote']}（目前 v{info['local']}）。\n\n要下載到 app/ 資料夾嗎？下載後按「套用」才會寫進 Claude Code。"):
            return

        def job():
            try:
                appdir.download_update(self.lay, self._log)
            except Exception as e:  # noqa: BLE001
                self._log(f"❌ 下載失敗：{type(e).__name__}: {e}")
                return
            self.repo = appdir.effective_repo(self.lay)
            if FROZEN and appdir.code_changed_since(REPO, self.repo):
                self._log(f"⚠️ 新版改了安裝器程式碼：規則／工具可直接套用，但視窗功能要換新執行檔才會更新 → {appdir.RELEASES_URL}")
        self._run_bg(job)

    def do_usage(self):
        def job():
            u = gm.refresh_usage(self.lay, PY)
            self.q.put(("usage", u["text"]))
            self._log(u["text"])
        self._run_bg(job, refresh_after=False)

    def do_selftest(self):
        msg = ("會用全新的無頭 Claude Code 對話重跑 9 道題（停車場 TDX、PowerShell 編碼、影片逐字稿、即時數值 API、"
               "程式庫文件、影片數據與截圖、國外空品、影片動作 Gemini、Chrome 開頁），比對它實際用了哪些工具。"
               + chr(10) * 2 + "通常 20～40 分鐘（每題上限 9 分鐘，最壞約 80 分鐘）、用掉約九場短對話的用量；Chrome 題需要瀏覽器開著。"
               + chr(10) + "注意：測試中 Claude 會自己執行指令、寫檔、讀網頁，沒有人逐步確認；它只在一個空的暫存資料夾工作，但讀到的網頁內容是不受信任的。結果會逐題印在下方紀錄。繼續？")
        ans = messagebox.askyesnocancel("自我測試", msg + chr(10) * 2 + "是＝只跑快測 3 題（PowerShell 編碼、即時數值 API、影片逐字稿，約 10 分鐘）　否＝全部 9 題　取消＝不跑")
        if ans is None:
            return
        smoke = bool(ans)

        def job():
            self._log(f"=== 自我測試開始（claude -p × {3 if smoke else 9}）===")
            code = selftest.run(log=self._log, report_dir=self.lay.home / "state" / "selftest-reports", smoke=smoke)
            self._log(f"=== 自我測試{'全部通過' if code == 0 else '有題目未通過（見 ❌）'} ===")
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
        inc = messagebox.askyesnocancel("匯出設定", "要把金鑰一起匯出嗎？\n\n是＝含金鑰明文（方便搬到新裝置，檔案要妥善保管、不可分享）\n否＝只匯出開關與數值\n取消＝不匯出\n\n（環境安裝如 ffmpeg、PowerShell 7 不在設定檔內，新裝置開視窗後按安裝鈕）")
        if inc is None:
            return
        p = filedialog.asksaveasfilename(title="匯出設定" + ("（含金鑰）" if inc else "（不含金鑰）"), defaultextension=".json",
                                         initialfile="claude-dev-system-profile" + ("-with-keys" if inc else "") + ".json")
        if not p:
            return
        cur = gm._local(self.lay).get("keys") or {}
        Path(p).write_text(json.dumps(gm.export_profile(self.state, self._collect(), include_keys=bool(inc), current_keys=cur), ensure_ascii=False, indent=2), encoding="utf-8")
        self._log(f"已匯出 {p}" + ("（含金鑰明文，請妥善保管）" if inc else "（不含金鑰）"))

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
        self.tc_var.set(bool(f.task_check.get("enabled")))
        self.tc_min_var.set(str(int(f.task_check.get("minutes", gm.DEFAULT_TASK_CHECK["minutes"]))))
        self.dl_var.set(f.download_dir or "")
        self.five_var.set(str(f.thresholds.get("fiveHour", self.five_var.get())))
        self.seven_var.set(str(f.thresholds.get("sevenDay", self.seven_var.get())))
        for n, mv in self.mode_vars.items():
            mv.set(MODE_LABEL.get(f.key_modes.get(n), "免費優先"))
        if f.chrome_default_enabled is not None and self.state["chrome"]["default_enabled"] is not None:
            self.chrome_var.set(f.chrome_default_enabled)
        n_keys = 0
        for n, v in f.keys.items():
            if v and n in self.key_vars:
                self.key_vars[n].set(v)
                n_keys += 1
        for n, v in f.key_notes.items():
            if v is not None and n in self.note_vars:
                self.note_vars[n].set(v)
        self._log(f"已匯入 {p}" + (f"（含 {n_keys} 把金鑰，按套用才寫入）" if n_keys else "（不含金鑰）"))
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
            if self.busy:
                messagebox.showinfo("稍等", "有工作正在執行")
                return
            if messagebox.askyesno("還原", f"用 {at} 的備份覆蓋現在的 settings.json？（現在的會先另存一份 -before-restore 備份）"):
                gm.restore_backup(self.lay, p)
                self._log(f"已還原 settings.json ← {p}")
                w.destroy()
                self.refresh()
        ttk.Button(w, text="還原選取的備份", command=restore).pack(pady=4)

    def do_uninstall(self):
        if not messagebox.askyesno("解除安裝", "只移除這套工具加進去的東西：\n• settings.json 的兩條 hook 與 env\n• CLAUDE.md 的標記區塊\n• 它註冊的 MCP\n• 規則／工具檔與 4 個 skill\n\n"
                                            "不會移除：pip 裝的 yt-dlp／faster-whisper、ffmpeg、PowerShell 7、Chrome 擴充、Python、Claude Code、金鑰檔 local.json、state/usage.json、這個設定程式本身。會順便刪 state/selftest-reports。\n\n確定？"):
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
    ap.add_argument("--selfcheck", metavar="輸出檔", help="不開視窗：把狀態寫成 JSON 到指定檔後結束（執行檔冒煙測試用）")
    a = ap.parse_args(argv)
    if a.selfcheck:
        try:
            lay = Layout(claude_home(a.claude_home))
            repo = appdir.effective_repo(lay)
            s = gm.read_state(lay, repo=repo, python=PY if FROZEN else None, importer=gm.system_importer(PY) if FROZEN else gm.video.default_importer)
            out = {"frozen": FROZEN, "repo": str(repo), "repo_version": s["repo_version"], "installed": s["installed"], "version": s["version"],
                   "python": PY, "env": {k: [v.ok, v.detail] for k, v in s["env"].items()}, "keys_present": sum(1 for k in s["keys"].values() if k["present"]),
                   "servers": list(s["web"]["servers"])}
            Path(a.selfcheck).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            return 0
        except Exception:  # noqa: BLE001  視窗模式沒有主控台，錯誤要寫進檔案才看得到（CI 用）
            import traceback
            Path(a.selfcheck).write_text(json.dumps({"error": traceback.format_exc()}, ensure_ascii=False, indent=1), encoding="utf-8")
            return 1
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
