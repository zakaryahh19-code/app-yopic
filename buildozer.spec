[app]
title = Yopic
package.name = yopic
package.domain = org.yopic.app
source.dir =.
source.include_exts = py,png,jpg,kv,atlas,ico
source.include_patterns = assets/*
version = 0.1

# هذا هو التركيبة التي تعمل 100% الآن
requirements = python3==3.11.6,kivy==2.3.1,pillow,pyjnius,android

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
presplash.color = #000000

# صلاحيات تعمل من أندرويد 7 إلى 14
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_STATE,CHANGE_NETWORK_STATE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license_agreements = True
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True
android.request_legacy_external_storage = True
android.manifest.application_attributes = android:usesCleartextTraffic="true"

# تثبيت نسخة p4a المستقرة قبل Python 3.14
p4a.branch = v2024.01.21
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
