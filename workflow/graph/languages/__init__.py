from . import javascript, python, typescript

REGISTRY = {}
for _module in (python, javascript, typescript):
    for _ext in _module.EXTENSIONS:
        REGISTRY[_ext] = _module
