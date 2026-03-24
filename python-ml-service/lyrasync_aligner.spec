# lyrasync_aligner.spec
# Run with: pyinstaller lyrasync_aligner.spec

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# Collect data files needed by each dependency
datas = []
datas += collect_data_files('faster_whisper')
datas += collect_data_files('demucs')
datas += collect_data_files('torch')
datas += collect_data_files('torchaudio')

# Collect dynamic libraries (especially torch's .dll files on Windows)
binaries = []
binaries += collect_dynamic_libs('torch')
binaries += collect_dynamic_libs('torchaudio')

a = Analysis(
    ['src/app.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        # FastAPI / uvicorn
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # Demucs
        'demucs',
        'demucs.pretrained',
        'demucs.apply',
        'demucs.htdemucs',
        'demucs.hdemucs',
        'demucs.states',
        # faster-whisper
        'faster_whisper',
        # Audio
        'soundfile',
        'torchaudio.transforms',
        'torchaudio.functional',
        # Other
        'numpy',
        'scipy',
        'einops',
        'diffq',
        'julius',
        'openai_whisper',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude CUDA — CPU only build
        'torch.cuda',
        'torch.distributed',
        'torch.nn.parallel',
        # Exclude unused large packages
        'matplotlib',
        'tkinter',
        'PIL',
        'cv2',
        'sklearn',
        'pandas',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='lyrasync-aligner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX compression causes issues with torch dlls
    console=True,       # Keep console=True so Electron can read stdout/stderr
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='lyrasync-aligner',
)
