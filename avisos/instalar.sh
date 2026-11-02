#!/bin/sh
# Compila e instala ~/Applications/CacaSN Avisos.app (notificação clicável)
set -e
cd "$(dirname "$0")"
APP="$HOME/Applications/CacaSN Avisos.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp Info.plist "$APP/Contents/"
swiftc -O main.swift -o "$APP/Contents/MacOS/CacaSNAvisos"
codesign --force -s - "$APP"
echo "instalado: $APP"
