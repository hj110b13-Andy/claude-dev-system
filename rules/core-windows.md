
## Windows 環境（只在 Windows 安裝時併入）

- PowerShell 工具是 **PowerShell 7（pwsh）** 時：支援 `&&`、`||`、三元運算子、`??`，`Get-Content`／`Invoke-RestMethod` 預設 UTF-8；Python 子程序由 `PYTHONUTF8=1` 強制 UTF-8（`install.py web` 寫進 settings.json 的 env）。
- **系統碼頁可能仍是 950**（台灣 Windows 預設），`powershell.exe`（Windows PowerShell 5.1）也還在。凡是 `.ps1` 可能被 5.1 執行的情況（工作排程器、別台沒裝 pwsh 的電腦、明確呼叫 `powershell.exe`），仍須：含中文的腳本存成 **UTF-8 with BOM**；腳本內 `Get-Content` 讀可能含中文的檔案一律加 `-Encoding UTF8`（無 BOM 的 UTF-8 檔，例如 Claude 用 Write 寫出的，5.1 會用 ANSI 誤讀）。
- 從 Bash 工具啟動 `pwsh` 時先 `[Console]::OutputEncoding=[Text.Encoding]::UTF8`，否則輸出到管線仍用系統碼頁。
