# @EXPECTED exit 0
# pythonw 启动 run.pyw：窗口出现、设备扫描完成、录音产生文件、干净退出
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

targets = []


def cb(hwnd, lp):
    if not user32.IsWindowVisible(hwnd):
        return True
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return True
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    if "系统音频采集" in buf.value:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        targets.append((hwnd, pid.value))
    return True


def find_windows():
    targets.clear()
    user32.EnumWindows(WNDENUMPROC(cb), None)
    return list(targets)


# 清理旧实例
for _ in range(40):
    if not find_windows():
        break
    time.sleep(0.5)
if find_windows():
    for hwnd, pid in find_windows():
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
    time.sleep(3)

started = datetime.now()
cfg_path = Path(os.environ["APPDATA"]) / "Orbit" / "config.json"

# 强制 WAV 输出，保证不依赖 FFmpeg
if cfg_path.exists():
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("settings", {})["output_format"] = "wav"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

p = subprocess.Popen(["pythonw", "run.pyw"])
print("launched pid", p.pid)

hwnd = 0
for _ in range(40):
    time.sleep(0.5)
    if p.poll() is not None:
        print("FAIL: pythonw exited early code=", p.returncode)
        sys.exit(1)
    hits = [h for h, pid in find_windows() if pid == p.pid]
    if hits:
        hwnd = hits[0]
        break
print("window hwnd", hwnd)
assert hwnd, "window not found"

time.sleep(3.0)  # 等设备扫描与监听启动

# 播放测试音（与录音并行）
fs = 48000
tone = (0.25 * np.sin(2 * np.pi * 997 * np.arange(fs * 25) / fs)).astype(np.float32)
sd.play(np.stack([tone, tone * 0.7], axis=1), fs, blocking=False)
time.sleep(0.5)

# 触发录音：局部快捷键 F9。每个键只发一次 down/up ——
# 发两对会被识别成“开始+停止”，导致录音在拿到任何音频帧之前就被取消。
user32.PostMessageW(hwnd, 0x0100, 0x78, 1)
user32.PostMessageW(hwnd, 0x0101, 0x78, 0xC0000001)

recording = False
for _ in range(20):
    time.sleep(0.5)
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process -Id %d -ErrorAction SilentlyContinue).Threads.Count" % p.pid],
        capture_output=True, text=True)
    try:
        nthreads = int(out.stdout.strip())
    except ValueError:
        continue
    if nthreads >= 28:  # 基线约 21，AudioCapture 启动后 +2 以上
        recording = True
        break
print("recording thread visible:", recording)
assert recording, "recorder did not start"

time.sleep(4.0)

# 停止：局部快捷键 F9 再次触发 = 停止录音（不要用 F11，它绑定的是“打开输出目录”，
# 其 Show-Object 前台切换会把后续按键送给资源管理器而不是本程序）
user32.PostMessageW(hwnd, 0x0100, 0x78, 1)
user32.PostMessageW(hwnd, 0x0101, 0x78, 0xC0000001)
time.sleep(3.0)

sd.stop()

settings = json.loads(cfg_path.read_text(encoding="utf-8")).get("settings", {}) \
    if cfg_path.exists() else {}
rec_dir = Path(settings.get("output_dir")
               or (Path(os.environ["USERPROFILE"]) / "Music" / "Orbit"))
files = [
    f for f in list(rec_dir.glob("*.wav")) + list(rec_dir.glob("*.flac"))
    if f.stat().st_mtime > started.timestamp() and f.stat().st_size > 2000
]
print("output dir:", rec_dir)
print("new files:", [f.name for f in files])
assert files, "no recording produced"

info = sf.info(str(files[0]))
print("info:", info.samplerate, "Hz", info.channels, "ch", info.subtype)
data, sr = sf.read(str(files[0]), dtype="float32", always_2d=True)
spec = np.abs(np.fft.rfft(data[:, 0], axis=0))
freqs = np.fft.rfftfreq(data.shape[0], 1 / sr)
print("peak freq:", round(float(freqs[np.argmax(spec)]), 2), "Hz")
assert 990 <= float(freqs[np.argmax(spec)]) <= 1005, "tone not captured"

# 干净退出
user32.PostMessageW(hwnd, 0x0010, 0, 0)
try:
    code = p.wait(timeout=8)
    print("exit code:", code)
    assert code == 0, "non-zero exit"
except subprocess.TimeoutExpired:
    p.kill()
    print("FAIL: did not exit on WM_CLOSE")
    sys.exit(1)

print("ALL GOOD")
