param([string]$Out, [string]$Text)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToWaveFile($Out)
$s.Speak($Text)
$s.Dispose()
if (Test-Path $Out) { Write-Output ("OK " + (Get-Item $Out).Length) } else { Write-Output "NOFILE" }
