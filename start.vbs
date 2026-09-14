Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.Run """C:\Users\LiYuanbo\AppData\Local\Programs\Python\Python312\pythonw.exe"" """ & scriptDir & "\src\tray_monitor.py""", 0, False
