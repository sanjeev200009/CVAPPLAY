Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\CVAPPLY"
WshShell.Run "cmd /c C:\CVAPPLY\run_daemon.bat", 0, False
