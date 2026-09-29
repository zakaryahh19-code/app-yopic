[app]
title = Yopic
package.name = yopic
package.domain = org.test
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ico
source.include_patterns = assets/*
version = 0.1

# kivymd غير مستعمل في main.py فتم حذفه (يبطئ البناء ويسبب مشاكل)
requirements = python3,kivy==2.3.0,pillow,pyjnius,android

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon.png

# ---------- شاشة البداية (بدل شعار Kivy) ----------
# ضع صورتك في assets/presplash.png (يفضّل PNG مربع أو عمودي، حوالي 512x512)
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #FFFFFF

# ---------- الصلاحيات (هذا هو سبب المشكلة الأساسي) ----------
# بدون INTERNET لا يعمل أي socket داخل الـ APK
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_MULTICAST_STATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO,QUERY_ALL_PACKAGES

# Android specific
android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True

# يسمح بالاتصال عبر http/TCP عادي على الشبكة المحلية
android.manifest.application_attributes = android:usesCleartextTraffic="true"

p4a.branch = master
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1
