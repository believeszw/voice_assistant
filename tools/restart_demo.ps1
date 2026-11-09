param()
$ErrorActionPreference = "Continue"
$root = "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\voice_assistant"
Set-Location $root
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Remove-Item "$root\tools\demo_e2e_report.txt","$root\tools\demo_e2e_assistant.log","$root\tools\demo_stdout.txt","$root\tools\demo_stderr.txt" -Force -ErrorAction SilentlyContinue
Start-Process -FilePath "C:\va-venv\Scripts\python.exe" `
  -ArgumentList "-u","tools\demo_e2e.py" `
  -WorkingDirectory $root `
  -RedirectStandardOutput "$root\tools\demo_stdout.txt" `
  -RedirectStandardError "$root\tools\demo_stderr.txt" `
  -NoNewWindow
"started " + (Get-Date).ToString("s") | Set-Content "$root\tools\demo_started.txt" -Encoding utf8
