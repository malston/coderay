from . import javascript, python

REGISTRY = {}
for _module in (python, javascript):
    for _ext in _module.EXTENSIONS:
        REGISTRY[_ext] = _module
