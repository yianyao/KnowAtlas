' run_hidden.vbs - launch a console program with no window (Task Scheduler silently).
' Usage: wscript.exe //nologo run_hidden.vbs "<exe>" "<arg1>" "<arg2>" ...
' Written ASCII-only on purpose: Windows Script Host reads this file as ANSI.

If WScript.Arguments.Count < 2 Then
  WScript.Quit 2
End If

Dim uv, workspace, cmd, sh
uv = WScript.Arguments(0)
workspace = WScript.Arguments(1)

cmd = Chr(34) & uv & Chr(34) & " run --with zstandard python " _
    & Chr(34) & workspace & "\tools\context_watcher.py" _
    & Chr(34) & " --once --workspace " & Chr(34) & workspace & Chr(34)

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = workspace
' 0 = hidden window, True = wait for exit (keeps the task's exit code meaningful)
Dim rc
rc = sh.Run(cmd, 0, True)
WScript.Quit rc