from . import python

REGISTRY = {}
for _module in (python,):
    for _ext in _module.EXTENSIONS:
        REGISTRY[_ext] = _module
