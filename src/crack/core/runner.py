"""Runs a pipeline flow against a shared state dict, common to any analysis."""

def run_flow(flow, shared, out_dir, dump_state):
    """Run `flow` against `shared`. On an unhandled exception, call
    `dump_state(shared, out_dir)` to write whatever partial progress exists,
    print where it landed, and re-raise."""
    try:
        flow.run(shared)
    except Exception:
        state_path = dump_state(shared, out_dir)
        print(f"\nPipeline failed. Wrote partial run state to {state_path}")
        raise
