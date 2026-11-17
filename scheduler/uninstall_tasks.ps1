# Removes all the bot tasks (the four harness commands and the dashboard).  powershell -ExecutionPolicy Bypass -File "<project folder>\scheduler\uninstall_tasks.ps1"
Get-ScheduledTask -TaskName "BTC bot - *" | Unregister-ScheduledTask -Confirm:$false
Write-Host "removed all 'BTC bot - *' tasks"
