' PaperMind Desktop Launcher (ASCII-only for all Windows locales)
Option Explicit
Dim fso, shell, root, pythonw, pythonExe
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
pythonExe = root & "\.venv\Scripts\python.exe"
If fso.FileExists(pythonw) Then
    shell.CurrentDirectory = root
    shell.Run Chr(34) & pythonw & Chr(34) & " -m backend.desktop", 0, False
ElseIf fso.FileExists(pythonExe) Then
    shell.CurrentDirectory = root
    shell.Run Chr(34) & pythonExe & Chr(34) & " -m backend.desktop", 0, False
Else
    MsgBox "PaperMind environment not found. Please run setup.ps1 in PowerShell first.", 48, "PaperMind Desktop"
    WScript.Quit 1
End If
