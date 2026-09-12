# toy_repo <script>alert(1)</script>

_Lens: beginner-tutorial_

_Generated 2026-01-01 from a snapshot of the code. May not reflect later changes._

A small service that reads orders off a queue and writes them to a ledger.

## Architecture

```mermaid
flowchart TD
    A0["Queue reader"]
    A1["Ledger writer"]
    A0 -- "hands each order to" --> A1
```

_Solid arrows are backed by a real import between the files each abstraction claims; dashed arrows are the model's judgment._

## Chapters

- [Queue <script>alert(1)</script> reader](01_queue_reader.md)
- [Ledger <img src=x onerror=alert(1)> writer](02_ledger_writer.md)