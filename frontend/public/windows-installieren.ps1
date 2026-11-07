# Trading-Bot fuer Windows installieren: legt Startmenue- und Desktop-Verknuepfung an,
# die die App in einem eigenen Fenster (ohne Browserleiste) oeffnet.
# Aufruf in PowerShell:  irm https://zentrix-tradingbot.fly.dev/windows-installieren.ps1 | iex
$ErrorActionPreference = 'Stop'
$url = 'https://zentrix-tradingbot.fly.dev/'
$dir = Join-Path $env:LOCALAPPDATA 'Trading-Bot'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$ico = Join-Path $dir 'trading-bot.ico'
try { Invoke-WebRequest ($url + 'favicon.ico') -OutFile $ico -UseBasicParsing } catch { $ico = $null }
$browser = @(
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) { Write-Host 'Microsoft Edge oder Google Chrome wurde nicht gefunden.' -ForegroundColor Red; return }
$shell = New-Object -ComObject WScript.Shell
foreach ($target in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
  $lnk = $shell.CreateShortcut((Join-Path $target 'Trading-Bot.lnk'))
  $lnk.TargetPath = $browser
  $lnk.Arguments = "--app=$url --user-data-dir=`"$dir\profil`""
  $lnk.WorkingDirectory = $dir
  $lnk.Description = 'Trading-Bot'
  if ($ico) { $lnk.IconLocation = $ico }
  $lnk.Save()
}
Write-Host 'Fertig: "Trading-Bot" liegt jetzt im Startmenue und auf dem Desktop.' -ForegroundColor Green
Start-Process $browser -ArgumentList "--app=$url", "--user-data-dir=`"$dir\profil`""
