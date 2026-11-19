"""Best-effort Windows desktop notification (no extra dependencies).

Title/message are passed via environment variables, never interpolated into the script,
so card text cannot inject PowerShell. Failures are swallowed by the caller.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 - fixed command, no shell
import sys

_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:KRT_TOAST_TITLE)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:KRT_TOAST_BODY)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""


def desktop_notify(title: str, body: str) -> None:
    if sys.platform != "win32":
        return
    env = {**os.environ, "KRT_TOAST_TITLE": title[:64], "KRT_TOAST_BODY": body[:200]}
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                       "WindowsPowerShell", "v1.0", "powershell.exe")
    subprocess.run(  # noqa: S603 - fixed absolute executable and arguments
        [exe, "-NoProfile", "-NonInteractive", "-Command", _PS],
        env=env, timeout=15, capture_output=True, check=False)
