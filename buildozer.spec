[app]

title = LumaIR
package.name = lumair
package.domain = app.lumair
source.dir = .
source.include_exts = py,json,png,jpg,atlas
source.exclude_dirs = .git,.buildozer,bin,__pycache__
icon.filename = %(source.dir)s/icon.png
version = 1.0.0
requirements = python3,kivy,pyjnius
orientation = portrait
fullscreen = 0
android.permissions = android.permission.TRANSMIT_IR
android.api = 36
android.minapi = 24
android.ndk = 28c
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.enable_androidx = True
p4a.bootstrap = sdl2
# Fixes p4a's pip self-upgrade venv corruption (BuildDependencyInstallError).
# Pin the upstream fix until it is included in a stable p4a release.
p4a.branch = develop
p4a.commit = d2ee8c54d9d42375a95f18159e950a119671cf63

# Keep the IR feature optional: the app can still open as a color editor on
# phones without an emitter, and reports that limitation in its status line.

[buildozer]
log_level = 2
warn_on_root = 1
