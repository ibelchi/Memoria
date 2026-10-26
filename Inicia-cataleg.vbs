Option Explicit
Dim shell, fso, base
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
On Error Resume Next
shell.Run "pythonw.exe """ & base & "\app.py""", 0, False
If Err.Number <> 0 Then MsgBox "No s'ha pogut trobar Python. Consulta README.md per iniciar el cataleg.", 48, "Cataleg de videos"
