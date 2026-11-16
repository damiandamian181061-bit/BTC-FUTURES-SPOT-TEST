# Optional, run ONCE as Administrator: stop the laptop sleeping / doing anything on lid close while plugged in,
# so the 00:01 / 20:55 / 21:00 / 22:55 UTC runs happen. (0 = never / do nothing.) Battery settings are left alone.
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setactive SCHEME_CURRENT
Write-Host "plugged-in: sleep never, hibernate never, lid close = do nothing. Keep it plugged in and on WiFi."
