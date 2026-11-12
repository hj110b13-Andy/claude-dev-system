# 專案盤點（project-scan.py 產生，2026-11-12T13:23:49）

原始碼 19、測試 18、腳本 9、設定 9、文件 33、資源 0、其他 1；語言：.py 37；依賴邊 51。

## 入口與啟動方式
- hooks/usage_guard.py（有 __main__ 守衛）
- installer/build_exe.py（有 __main__ 守衛）
- installer/gui.py（有 __main__ 守衛）
- installer/install.py（有 __main__ 守衛）
- installer/selfupdate_exe.py（有 __main__ 守衛）
- tools/agent-audit.py（有 __main__ 守衛）
- tools/cleanup.py（有 __main__ 守衛）
- tools/depgraph.py（有 __main__ 守衛）
- tools/moduleInventory.py（有 __main__ 守衛）
- tools/procs.py（有 __main__ 守衛）
- tools/progress-diff.py（有 __main__ 守衛）
- tools/project-scan.py（有 __main__ 守衛）
- tools/resgate.py（有 __main__ 守衛）
- tools/video.py（有 __main__ 守衛）

## 最大的檔（行數）
- hooks/usage_guard.py：2217 行
- installer/cds/gui_model.py：1360 行
- tools/video.py：1214 行
- installer/gui.py：1131 行
- installer/cds/commands.py：732 行
- tools/project-scan.py：621 行
- tools/cleanup.py：496 行
- tools/resgate.py：482 行
- tools/agent-audit.py：436 行
- installer/cds/web.py：344 行

## 循環依賴
- 無

## 被引用最多的模組（改到要走 cds-blast-radius）
- installer/cds/paths.py：被 9 個檔引用
- installer/cds/checks.py：被 6 個檔引用
- installer/cds/fsio.py：被 6 個檔引用
- installer/cds/__init__.py：被 5 個檔引用
- installer/cds/web.py：被 4 個檔引用
- installer/cds/commands.py：被 3 個檔引用
- installer/cds/appdir.py：被 2 個檔引用
- installer/cds/selftest.py：被 2 個檔引用
- installer/cds/manifest.py：被 2 個檔引用
- installer/cds/video.py：被 2 個檔引用

## 問題清單（門檻：單檔 > 800 行、循環依賴、≥10 個原始碼檔卻沒有測試）
- big-file：hooks/usage_guard.py — 2217 行 > 800
- big-file：installer/cds/gui_model.py — 1360 行 > 800
- big-file：tools/video.py — 1214 行 > 800（腳本）
- big-file：installer/gui.py — 1131 行 > 800

## 無法讀取的檔
- 無

## 設定檔
- .gitattributes
- .github/workflows/release.yml
- .github/workflows/tests.yml
- .gitignore
- config/compat.json
- config/dispatch-config.json
- config/selftest.json
- config/video.json
- config/web-sources.json

每個檔的雜湊在 `.claude/project-scan.json`；`python project-scan.py <root> --check` 列出自上次盤點後改過的檔。
