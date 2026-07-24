from setuptools import setup

APP = ['../src/pet_app.py']
OPTIONS = {
    'argv_emulation': False,
    'packages': ['webview'],
    'plist': {
        'LSUIElement': False,
    },
}

setup(
    app=APP,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
