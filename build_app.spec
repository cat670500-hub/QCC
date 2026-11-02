# -*- mode: python ; coding: utf-8 -*-

import os

datas = [
    ('templates', 'templates'),
    ('static', 'static'),
]

for optional_file in ['tprisweb.shh.org.tw.har', 'cert.pem', 'key.pem', '.env', 'settings.json', 'sms_settings.json']:
    if os.path.exists(optional_file):
        datas.append((optional_file, '.'))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'engineio.async_drivers.threading',
        'simple_websocket',
        'wsproto',
        'h11',
        'cryptography',
        'cryptography.x509',
        'cryptography.hazmat.backends.openssl',
        'ipaddress',
        'eporter_client'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Portable派遣系統',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Portable派遣系統',
)
