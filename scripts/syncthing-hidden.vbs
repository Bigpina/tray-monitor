Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\Program Files\syncthing-windows-amd64-v2.1.2\syncthing.exe"" serve --no-browser", 0, False
