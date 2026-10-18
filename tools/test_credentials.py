"""Test credentials for live checks: environment first, then the macOS Keychain.

``SCENARIO_API_KEY`` and ``SCENARIO_API_SECRET`` win (CI). On a development Mac
the key lives in the Keychain under the service ``Scenario for Maya tests``
(account = key id, password = secret). Nothing here prints the secret.
"""

import os
import subprocess
import sys

SERVICE = "Scenario for Maya tests"


def load():
    """``(key_id, secret)`` or ``("", "")`` when none is available."""
    key, secret = os.environ.get("SCENARIO_API_KEY", "").strip(), os.environ.get("SCENARIO_API_SECRET", "").strip()
    if key and secret:
        return key, secret
    if sys.platform != "darwin":
        return "", ""
    found = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE], capture_output=True, text=True)
    account = ""
    for line in found.stdout.splitlines():
        if line.strip().startswith('"acct"<blob>='):
            account = line.split("=", 1)[1].strip().strip('"')
    if not account:
        return "", ""
    secret = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"], capture_output=True, text=True).stdout.strip()
    return (account, secret) if secret else ("", "")
