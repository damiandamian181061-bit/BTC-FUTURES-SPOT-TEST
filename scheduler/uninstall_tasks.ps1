# Removes all the bot tasks (the four harness commands and the dashboard).  powershell -ExecutionPolicy Bypass -File "C:\Users\damia\Documents\BTC Strategy Project\scheduler\uninstall_tasks.ps1"
Get-ScheduledTask -TaskName "BTC bot - *" | Unregister-ScheduledTask -Confirm:$false
Write-Host "removed all 'BTC bot - *' tasks"
