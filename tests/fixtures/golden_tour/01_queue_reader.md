# Queue reader

The reader pulls one order at a time from the queue and hands it on.

```python
def read_one(queue):
    """Block until an order arrives, then return it."""
    return queue.get(timeout=30)
```

> A timeout is set so a stalled queue surfaces as an error rather than a hang.

| Setting | Value | Where |
| --- | --- | --- |
| `timeout` | 30s | `src/reader.py` |
| `batch` | 1 | `src/reader.py` |

Next, see [Ledger writer](02_ledger_writer.md).
