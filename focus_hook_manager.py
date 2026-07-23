import ctypes
import ctypes.wintypes as wintypes
import os

from config import get_asset_path, INTERNAL_DIR, APP_DIR

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

VirtualAllocEx = kernel32.VirtualAllocEx
VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
VirtualAllocEx.restype = wintypes.LPVOID

WriteProcessMemory = kernel32.WriteProcessMemory
WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
WriteProcessMemory.restype = wintypes.BOOL

CreateRemoteThread = kernel32.CreateRemoteThread
CreateRemoteThread.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD]
CreateRemoteThread.restype = wintypes.HANDLE

WaitForSingleObject = kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
WaitForSingleObject.restype = wintypes.DWORD

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

GetModuleHandleA = kernel32.GetModuleHandleA
GetModuleHandleA.argtypes = [wintypes.LPCSTR]
GetModuleHandleA.restype = wintypes.HMODULE

GetProcAddress = kernel32.GetProcAddress
GetProcAddress.argtypes = [wintypes.HMODULE, wintypes.LPCSTR]
GetProcAddress.restype = wintypes.LPVOID

GetExitCodeThread = kernel32.GetExitCodeThread
GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
GetExitCodeThread.restype = wintypes.BOOL

Module32First = kernel32.Module32First
Module32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
Module32First.restype = wintypes.BOOL

Module32Next = kernel32.Module32Next
Module32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
Module32Next.restype = wintypes.BOOL

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
INFINITE = 0xFFFFFFFF
WAIT_TIMEOUT = 0x00000102
REMOTE_THREAD_TIMEOUT_MS = 5000
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.CHAR * 256),
        ("szExePath", wintypes.CHAR * 260),
    ]


class SYSTEM_INFO(ctypes.Structure):
    _fields_ = [
        ("wProcessorArchitecture", wintypes.WORD),
        ("wReserved", wintypes.WORD),
        ("dwPageSize", wintypes.DWORD),
        ("lpMinimumApplicationAddress", wintypes.LPVOID),
        ("lpMaximumApplicationAddress", wintypes.LPVOID),
        ("dwActiveProcessorMask", ctypes.c_void_p),
        ("dwNumberOfProcessors", wintypes.DWORD),
        ("dwProcessorType", wintypes.DWORD),
        ("dwAllocationGranularity", wintypes.DWORD),
        ("wProcessorLevel", wintypes.WORD),
        ("wProcessorRevision", wintypes.WORD),
    ]


def is_process_64bit(pid):
    h_process = OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
    if not h_process:
        raise OSError(f"OpenProcess failed for PID {pid}, err={ctypes.get_last_error()}")
    try:
        si = SYSTEM_INFO()
        kernel32.GetNativeSystemInfo(ctypes.byref(si))
        is_os_64 = si.wProcessorArchitecture in (9, 12)
        if not is_os_64:
            return False
        IsWow64Process = kernel32.IsWow64Process
        IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        IsWow64Process.restype = wintypes.BOOL
        wow64 = wintypes.BOOL(False)
        if not IsWow64Process(h_process, ctypes.byref(wow64)):
            raise OSError(f"IsWow64Process failed, err={ctypes.get_last_error()}")
        return not bool(wow64.value)
    finally:
        CloseHandle(h_process)


def get_dll_path(is64):
    dll_name = "focus_hook_x64.dll" if is64 else "focus_hook_x86.dll"
    path = get_asset_path(dll_name)
    if path and os.path.exists(path):
        return path
    # PyInstaller --add-data assets;assets 时 DLL 也会在 INTERNAL_DIR/assets 下。
    candidates = [
        os.path.join(INTERNAL_DIR, "assets", dll_name),
        os.path.join(APP_DIR, "assets", dll_name),
        os.path.join(APP_DIR, dll_name),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(f"找不到 {dll_name}")


def inject_dll(pid, dll_path):
    dll_path = os.path.abspath(dll_path)
    if not os.path.exists(dll_path):
        raise FileNotFoundError(f"DLL not found: {dll_path}")

    dll_data = dll_path.encode("mbcs") + b"\x00"
    h_process = OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
    if not h_process:
        raise OSError(f"OpenProcess failed, err={ctypes.get_last_error()}")

    try:
        remote_addr = VirtualAllocEx(h_process, None, len(dll_data), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not remote_addr:
            raise OSError(f"VirtualAllocEx failed, err={ctypes.get_last_error()}")

        written = ctypes.c_size_t(0)
        buf = ctypes.create_string_buffer(dll_data)
        if not WriteProcessMemory(h_process, remote_addr, buf, len(dll_data), ctypes.byref(written)):
            raise OSError(f"WriteProcessMemory failed, err={ctypes.get_last_error()}")

        loadlib = GetProcAddress(GetModuleHandleA(b"kernel32.dll"), b"LoadLibraryA")
        if not loadlib:
            raise OSError(f"GetProcAddress(LoadLibraryA) failed, err={ctypes.get_last_error()}")

        h_thread = CreateRemoteThread(h_process, None, 0, loadlib, remote_addr, 0, None)
        if not h_thread:
            raise OSError(f"CreateRemoteThread failed, err={ctypes.get_last_error()}")

        try:
            wait_result = WaitForSingleObject(h_thread, REMOTE_THREAD_TIMEOUT_MS)
            if wait_result == WAIT_TIMEOUT:
                raise TimeoutError("注入 Hook 超时（5 秒）")
        finally:
            CloseHandle(h_thread)
        return True
    finally:
        CloseHandle(h_process)


def find_remote_module(pid, dll_name):
    target = os.path.basename(dll_name).lower()
    flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
    h_snap = kernel32.CreateToolhelp32Snapshot(flags, int(pid))
    if h_snap == wintypes.HANDLE(-1).value:
        raise OSError(f"CreateToolhelp32Snapshot(module) failed, err={ctypes.get_last_error()}")

    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(me)
    try:
        if not Module32First(h_snap, ctypes.byref(me)):
            return None
        while True:
            name = me.szModule.decode("mbcs", errors="ignore").strip("\x00").lower()
            if name == target:
                return int(me.hModule)
            if not Module32Next(h_snap, ctypes.byref(me)):
                break
    finally:
        CloseHandle(h_snap)
    return None


def unload_dll(pid, dll_name):
    remote_module = find_remote_module(pid, dll_name)
    if not remote_module:
        return False

    h_process = OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
    if not h_process:
        raise OSError(f"OpenProcess failed, err={ctypes.get_last_error()}")

    try:
        freelib = GetProcAddress(GetModuleHandleA(b"kernel32.dll"), b"FreeLibrary")
        if not freelib:
            raise OSError(f"GetProcAddress(FreeLibrary) failed, err={ctypes.get_last_error()}")

        h_thread = CreateRemoteThread(h_process, None, 0, freelib, remote_module, 0, None)
        if not h_thread:
            raise OSError(f"CreateRemoteThread(FreeLibrary) failed, err={ctypes.get_last_error()}")

        try:
            wait_result = WaitForSingleObject(h_thread, REMOTE_THREAD_TIMEOUT_MS)
            if wait_result == WAIT_TIMEOUT:
                raise TimeoutError("卸载 Hook 超时（5 秒）")
            code = wintypes.DWORD(0)
            if GetExitCodeThread(h_thread, ctypes.byref(code)) and code.value == 0:
                raise OSError("FreeLibrary 返回失败，Hook 可能仍在目标进程中")
        finally:
            CloseHandle(h_thread)
        return True
    finally:
        CloseHandle(h_process)


def hook_process(pid):
    is64 = is_process_64bit(pid)
    dll_path = get_dll_path(is64)
    dll_name = os.path.basename(dll_path)
    # 上次工具异常退出时 DLL 可能仍留在游戏中。复用已有模块，避免重复注入同名 Hook。
    existing_module = find_remote_module(pid, dll_name)
    if existing_module:
        return {
            "pid": int(pid),
            "dll_name": dll_name,
            "dll_path": dll_path,
            "bits": 64 if is64 else 32,
            "reused": True,
        }
    inject_dll(pid, dll_path)
    return {
        "pid": int(pid),
        "dll_name": dll_name,
        "dll_path": dll_path,
        "bits": 64 if is64 else 32,
        "reused": False,
    }


def unhook_process(pid, dll_name):
    return unload_dll(int(pid), dll_name)
