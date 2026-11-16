# Windows Scheduled Task Setup for AI Job Application Agent
param(
    [string]$RunTime = "06:00"
)

$TaskName = "JobApplicationAgent"
$ProjectDir = $PSScriptRoot
$BatPath = Join-Path $ProjectDir "run_daily.bat"

Write-Host "Registering Scheduled Task: $TaskName at $RunTime daily..." -ForegroundColor Cyan

try {
    # 1. Action: run run_daily.bat with --scheduled flag in the project directory
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$BatPath`" --scheduled`"" -WorkingDirectory $ProjectDir

    # 2. Trigger: Daily at specified time
    $trigger = New-ScheduledTaskTrigger -Daily -At $RunTime

    # 3. Settings: Wake computer, start when available if missed, allow on battery
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun

    # 4. Register task under current user
    $task = Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction Stop

    Write-Host "[SUCCESS] Windows Scheduled Task '$TaskName' registered successfully!" -ForegroundColor Green
    Write-Host "  Daily Time: $RunTime IST" -ForegroundColor Yellow
    Write-Host "  Options: Wake-to-run enabled, Start-when-available enabled." -ForegroundColor Yellow
    Write-Host "  Log Output: $ProjectDir\data\output\daily_run.log" -ForegroundColor Yellow
}
catch {
    Write-Warning "PowerShell registration encountered: $_"
    Write-Host "Attempting fallback with schtasks.exe..." -ForegroundColor Cyan
    schtasks.exe /create /tn $TaskName /tr "`"$BatPath`" --scheduled" /sc daily /st $RunTime /f
}
