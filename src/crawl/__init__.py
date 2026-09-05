"""crawl: analyses that read a codebase and write an overview of it."""

# The package relies on assert statements: nearly every normalize() rejects a
# wrong-shaped model reply with one (SmartCrawl's raises ValueError), and that
# AssertionError is what makes json_call and yaml_call retry; the post-call
# output checks are asserts too. python -O strips them, so a bad reply would
# pass straight through to the renderer. Refusing here is one line where
# converting some fifty asserts would be a sweep nobody would keep up
# (coderay-5wu.19).
if not __debug__:
    raise SystemExit("crawl does not run with Python optimisation on (python -O, or PYTHONOPTIMIZE "
                     "set): it relies on assert statements to reject bad model replies and retry "
                     "them. Run it without -O and with PYTHONOPTIMIZE unset.")
