' PaperMind 独立桌面端无黑框双击启动器
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    MsgBox "未检测到本地运行环境，请先右键使用 PowerShell 运行一次 setup.ps1 完成初始化。", 48, "PaperMind 桌面端"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run """" & pythonw & """ -m backend.desktop", 0, False
