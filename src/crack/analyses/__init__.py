"""Registry of available analyses: name -> module implementing the analysis
interface (NAME, build_flow, add_arguments, init_shared, run)."""
from crack.analyses import architecture, backend, interfaces, schema, tour

ANALYSES = {a.NAME: a for a in (tour, backend, architecture, interfaces, schema)}
