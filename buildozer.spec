[app]
title = Yopic
package.name = yopic
package.domain = org.yopic.app
source.dir =.
source.include_exts = py,png,jpg,kv,atlas,ico
source.include_patterns = assets/*
version = 0.1
requirements = python3==3.11.6,kivy==2.3.1,pillow,pyjnius,android

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
presplash.color = #000000

android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_STATE,CHANGE_NETWORK_STATE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33
android.build_tools_version = 33.0.2
android.accept_sdk_license_agreements = True
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True
android.request_legacy_external_storage = True
android.manifest.application_attributes = android:usesCleartextTraffic="true"

p4a.branch = v2024.01.21
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
