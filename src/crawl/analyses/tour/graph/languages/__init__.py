from . import go, javascript, python, typescript

REGISTRY = {}
for _module in (python, javascript, typescript, go):
    for _ext in _module.EXTENSIONS:
        REGISTRY[_ext] = _module
