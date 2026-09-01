"""Registry of available analyses: name -> module implementing the analysis
interface (NAME, build_flow, add_arguments, init_shared, run)."""
from crack.analyses import tour

ANALYSES = {tour.NAME: tour}
