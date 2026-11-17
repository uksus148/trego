"""Windows Credential Manager adapter. Never falls back to a plaintext file."""

import ctypes
import os
from ctypes import wintypes


class Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


class Vault:
    def __init__(self):
        self.api = ctypes.WinDLL("Advapi32.dll", use_last_error=True) if os.name == "nt" else None
        if self.api:
            self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
            self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                         ctypes.POINTER(ctypes.POINTER(Credential))]
            self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            self.api.CredFree.argtypes = [ctypes.c_void_p]

    @staticmethod
    def target(provider):
        if provider not in {"groq", "exa", "anthropic", "launcher"}:
            raise ValueError("Unknown credential provider")
        return "trego.agent-v2-lab/" + provider

    def read(self, provider):
        if not self.api:
            return None
        pointer = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(self.target(provider), 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise OSError("Credential Manager unavailable")
        try:
            return ctypes.string_at(pointer.contents.CredentialBlob,
                                    pointer.contents.CredentialBlobSize).decode("utf-16-le")
        finally:
            self.api.CredFree(pointer)

    def write(self, provider, value):
        if not self.api:
            raise OSError("Windows Credential Manager unavailable; use session-only storage")
        raw = value.encode("utf-16-le")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = Credential(Type=1, TargetName=self.target(provider), CredentialBlobSize=len(raw),
                                CredentialBlob=blob, Persist=2, UserName="agent-lab")
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise OSError("Credential Manager could not save this key")

    def delete(self, provider):
        if self.api and not self.api.CredDeleteW(self.target(provider), 1, 0):
            if ctypes.get_last_error() != 1168:
                raise OSError("Credential Manager could not delete this key")
