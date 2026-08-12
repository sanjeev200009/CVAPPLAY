# PowerShell Script to register CV Apply as a Windows Scheduled Task (Cron equivalent)

$taskName = "CVApplyAutoEngine"
$pythonExe = "C:\CVAPPLY\.venv\Scripts\python.exe"
$workingDir = "C:\CVAPPLY"
$arguments = "-m cvapply.daemon --submit --interval 3.0 --batch-limit 6"

# Create action to run python daemon
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $workingDir

# Trigger at system startup / user logon, repeating continuously
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

# Register the task
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggerLogon -Settings $settings -Description "CV Apply automated background job sourcing, scoring, and application engine"
    Write-Host "✅ Successfully registered Windows Scheduled Task: $taskName"
    Write-Host "It will automatically run in the background on startup."
} catch {
    Write-Host "⚠️ Note: Run PowerShell as Administrator to register persistent scheduled task, or launch run_daemon.bat directly."
}
