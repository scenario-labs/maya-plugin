"""OS credential stores for secrets: refresh tokens, API secrets, the agent token.

Secrets never go in the scene, optionVars, ``userPrefs.mel``, ``Maya.env``,
settings files or logs. One store per OS, chosen at runtime:

- macOS: the login Keychain through ``/usr/bin/security``. Items written by
  that one program are readable by it without a prompt from Maya, ``mayapy``
  and every Maya version alike (an item written by Maya itself would be
  trusted for that Maya binary only, and a Maya update would bring the
  "wants to use your confidential information" prompt). Secrets travel on
  stdin as hexadecimal, never on the command line.
- Windows: Credential Manager through ``CredWriteW`` and ``CredReadW``
  (ctypes). Generic credentials, target ``Scenario for Maya/<account>``.
- Linux: the Secret Service through ``secret-tool``, secret on stdin.
- Anywhere else, or when the store is unavailable: a JSON file readable only
  by the user in the plug-in's folder. ``insecure`` is then True and the
  Connection tab says so.

``SCENARIO_MAYA_CREDSTORE`` forces ``file`` or ``memory`` (tests, CI).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading

from . import errors
from .paths import user_file

SERVICE = "Scenario for Maya"


class CredentialStore:
    name = "base"
    insecure = False

    def get(self, account: str) -> str | None:
        raise NotImplementedError

    def set(self, account: str, secret: str) -> None:
        raise NotImplementedError

    def delete(self, account: str) -> bool:
        raise NotImplementedError


class MemoryStore(CredentialStore):
    name = "memory"
    insecure = True

    def __init__(self) -> None:
        self._items: dict = {}

    def get(self, account: str) -> str | None:
        return self._items.get(account)

    def set(self, account: str, secret: str) -> None:
        self._items[account] = secret

    def delete(self, account: str) -> bool:
        return self._items.pop(account, None) is not None


class FileStore(CredentialStore):
    """Owner-only JSON file. Last resort: it is plain text on disk."""

    name = "file"
    insecure = True
    _lock = threading.Lock()

    def __init__(self, path: str | None = None) -> None:
        self.path = path or user_file("credentials.json")

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.path + ".tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(tmp, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        if not sys.platform.startswith("win"):
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def get(self, account: str) -> str | None:
        with self._lock:
            value = self._read().get(account)
        return value if isinstance(value, str) else None

    def set(self, account: str, secret: str) -> None:
        with self._lock:
            data = self._read()
            data[account] = secret
            self._write(data)

    def delete(self, account: str) -> bool:
        with self._lock:
            data = self._read()
            found = data.pop(account, None) is not None
            if found:
                self._write(data)
            return found


class MacKeychainStore(CredentialStore):
    name = "macOS Keychain"
    _tool = "/usr/bin/security"

    def __init__(self, service: str = SERVICE) -> None:
        self.service = service

    @classmethod
    def available(cls) -> bool:
        return sys.platform == "darwin" and os.path.exists(cls._tool)

    def _run(self, args: list, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([self._tool, *args], input=stdin, capture_output=True, text=True, timeout=20)

    def get(self, account: str) -> str | None:
        result = self._run(["find-generic-password", "-s", self.service, "-a", account, "-w"])
        if result.returncode == 44:  # errSecItemNotFound
            return None
        if result.returncode != 0:
            raise errors.CredentialStoreError(f"Keychain read failed (code {result.returncode}).")
        return result.stdout.rstrip("\n")

    def set(self, account: str, secret: str) -> None:
        command = (
            f"add-generic-password -U -s {_quote(self.service)} -a {_quote(account)} "
            f"-l {_quote(self.service)} -X {secret.encode('utf-8').hex()}\n"
        )
        result = self._run(["-i"], stdin=command)
        if result.returncode != 0 or "error" in (result.stderr or "").lower():
            raise errors.CredentialStoreError("Keychain write failed.", hint="Unlock the login keychain and try again.")

    def delete(self, account: str) -> bool:
        result = self._run(["delete-generic-password", "-s", self.service, "-a", account])
        return result.returncode == 0


class SecretToolStore(CredentialStore):
    name = "Secret Service"

    def __init__(self, service: str = SERVICE) -> None:
        self.service = service

    @staticmethod
    def available() -> bool:
        return sys.platform.startswith("linux") and bool(shutil.which("secret-tool")) and bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))

    def _attrs(self, account: str) -> list:
        return ["service", self.service, "account", account]

    def get(self, account: str) -> str | None:
        result = subprocess.run(["secret-tool", "lookup", *self._attrs(account)], capture_output=True, text=True, timeout=20)
        if result.returncode != 0 or not result.stdout:
            return None
        return result.stdout.rstrip("\n")

    def set(self, account: str, secret: str) -> None:
        result = subprocess.run(
            ["secret-tool", "store", f"--label={self.service}", *self._attrs(account)], input=secret, capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            raise errors.CredentialStoreError("Secret Service write failed.")

    def delete(self, account: str) -> bool:
        return subprocess.run(["secret-tool", "clear", *self._attrs(account)], capture_output=True, timeout=20).returncode == 0


class WindowsCredentialStore(CredentialStore):
    """Generic credentials in Credential Manager. Blob limit 2,560 bytes."""

    name = "Windows Credential Manager"
    _MAX_BLOB = 2560

    def __init__(self, service: str = SERVICE) -> None:
        self.service = service
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        advapi.CredWriteW.restype = wintypes.BOOL
        advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        advapi.CredReadW.restype = wintypes.BOOL
        advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        advapi.CredDeleteW.restype = wintypes.BOOL
        advapi.CredFree.argtypes = [ctypes.c_void_p]
        advapi.CredFree.restype = None
        self._ctypes = ctypes
        self._cred_type = CREDENTIALW
        self._api = advapi

    @staticmethod
    def available() -> bool:
        return sys.platform.startswith("win")

    def _target(self, account: str) -> str:
        return f"{self.service}/{account}"

    def get(self, account: str) -> str | None:
        ctypes = self._ctypes
        pointer = ctypes.POINTER(self._cred_type)()
        if not self._api.CredReadW(self._target(account), 1, 0, ctypes.byref(pointer)):
            code = ctypes.get_last_error()
            if code == 1168:  # ERROR_NOT_FOUND
                return None
            raise errors.CredentialStoreError(f"Credential Manager read failed (code {code}).")
        try:
            cred = pointer.contents
            return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode("utf-8")
        finally:
            self._api.CredFree(pointer)

    def set(self, account: str, secret: str) -> None:
        ctypes = self._ctypes
        blob = secret.encode("utf-8")
        if len(blob) > self._MAX_BLOB:
            raise errors.CredentialStoreError("Secret too long for Credential Manager.")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = self._cred_type()
        cred.Type = 1  # CRED_TYPE_GENERIC
        cred.TargetName = self._target(account)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = account
        if not self._api.CredWriteW(ctypes.byref(cred), 0):
            raise errors.CredentialStoreError(f"Credential Manager write failed (code {ctypes.get_last_error()}).")

    def delete(self, account: str) -> bool:
        return bool(self._api.CredDeleteW(self._target(account), 1, 0))


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


_DEFAULT: CredentialStore | None = None
_DEFAULT_LOCK = threading.Lock()


def default_store() -> CredentialStore:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is not None:
            return _DEFAULT
        forced = os.environ.get("SCENARIO_MAYA_CREDSTORE", "").strip().lower()
        if forced == "memory":
            _DEFAULT = MemoryStore()
        elif forced == "file":
            _DEFAULT = FileStore()
        elif MacKeychainStore.available():
            _DEFAULT = MacKeychainStore()
        elif WindowsCredentialStore.available():
            try:
                _DEFAULT = WindowsCredentialStore()
            except OSError:
                _DEFAULT = FileStore()
        elif SecretToolStore.available():
            _DEFAULT = SecretToolStore()
        else:
            _DEFAULT = FileStore()
        return _DEFAULT


def set_default_store(store: CredentialStore | None) -> None:
    """Tests and the Maya layer may replace the store; ``None`` resets the choice."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = store
