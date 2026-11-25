#!/bin/bash
# 构建 "Hetu Agent.app" 供人工测试。用法: bash packaging/macos/build_macos_app.sh
# 架构: 编译 launcher.c -> Contents/MacOS/HetuAgent; 包内自带 python 二进制
#       (pyvenv.cfg 指向宿主 stdlib) -> NSApplication 主 bundle 即本 app,
#       菜单栏/Dock 显示 "Hetu Agent" 与自定义图标。源码树整体拷入 Resources/src,
#       测试/脚本按仓库相对路径工作。零第三方依赖。
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# 密封宿主环境: hetu.guard 对 HETU_HOME/HETU_DB fail-closed，
# 构建期任何内核预检不得继承把这些变量指进旧产品树的 shell 环境。
unset HETU_HOME HETU_DB
APP="${1:-$HOME/Applications/Hetu Agent.app}"
[[ "$APP" = /* && "$APP" = *.app && ! -e "$APP" ]] || {
  echo "请指定尚不存在的 .app 绝对路径: $APP" >&2
  exit 1
}
RES="$APP/Contents/Resources"
ICON_SRC="${HETU_ICON:-$HOME/Downloads/hongyunicn.png}"
[ -f "$ICON_SRC" ] || { echo "缺少图标源图: $ICON_SRC"; exit 1; }

mkdir -p "$APP/Contents/MacOS" "$RES/src"

# 1) 图标
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
ICONSET="$SCRATCH/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 64 128 256 512; do
  sips -z $s $s "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s*2)); sips -z $d $d "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"
sips -z 128 128 "$ICON_SRC" --out "$RES/hetu-icon.png" >/dev/null

# 2) 启动器: 嵌入 libpython 的 C launcher(绕过框架 python 的 Python.app re-exec)
#    stdlib 由 Contents/MacOS/pyvenv.cfg 的 home 指向宿主框架
cd "$REPO"
PYREAL=$(/usr/bin/python3 -c 'import objc,os,sys; print(os.path.realpath(sys.executable))')
FWP=$(/usr/bin/python3 -c 'import sysconfig;print(sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX"))')
# Xcode 的 sysconfig include 路径不可靠, 从框架实际布局推导
PYVER=$(/usr/bin/python3 -c 'import sys;print("python%d.%d" % sys.version_info[:2])')
HDR="$(dirname "$(dirname "$PYREAL")")/include/$PYVER"
[ -f "$HDR/Python.h" ] || { echo "找不到 Python.h: $HDR"; exit 1; }
cat > "$APP/Contents/MacOS/pyvenv.cfg" <<CFG
home = $(dirname "$PYREAL")
include-system-site-packages = true
CFG
cc -O2 -I"$HDR" -F"$FWP" -framework Python3 -Wl,-rpath,"$FWP" \
   packaging/macos/launcher.c -o "$APP/Contents/MacOS/HetuAgent"
chmod +x "$APP/Contents/MacOS/HetuAgent"

# 3) 源码树(测试/脚本按 ROOT 相对路径工作)
cp -R hetu scripts tests "$RES/src/"
cp pyproject.toml "$RES/src/"
cp packaging/macos/gui.py packaging/macos/gui.html packaging/macos/local_chat.py packaging/macos/model_providers.py packaging/macos/memory_cloud.py packaging/macos/smoke_model.py "$RES/"
cp -R packaging/macos/hasu_port "$RES/"

VERSION=$(/usr/bin/python3 -c 'from hetu import __version__; print(__version__)')
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Hetu Agent</string>
  <key>CFBundleDisplayName</key><string>Hetu Agent</string>
  <key>CFBundleIdentifier</key><string>dev.hongyun.hetu-agent</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>HetuAgent</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
touch "$APP"

# 5) 冒烟: 启动器以 -m 透传方式跑内核自检(无 GUI); 失败即退出非零
LOG="$SCRATCH/cli.log"
if "$APP/Contents/MacOS/HetuAgent" -m hetu status >"$LOG" 2>&1; then
  tail -1 "$LOG"
else
  echo "SMOKE FAILED:"; cat "$LOG"; exit 1
fi
echo "built: $APP"
