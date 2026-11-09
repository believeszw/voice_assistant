param()
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\voice_assistant"
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
"started: " + (Get-Date).ToString("s") | Set-Content -Path "tools\demo_started.txt" -Encoding utf8
Start-Process -FilePath "C:\va-venv\Scripts\python.exe" `
  -ArgumentList "-u","tools\demo_e2e.py" `
  -WorkingDirectory "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\voice_assistant" `
  -NoNewWindow
