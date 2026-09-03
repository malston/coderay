# Acme Booking <script>alert(1)</script>: schema

_Rooms, holds and the invoices that follow them._

Acme Booking is four tables around one hinge, with money bolted on a year later.

## The tour

**Product:** Acme Booking
**Schema one-liner:** Rooms, holds and the invoices that follow them.

```mermaid
erDiagram
  users ||--o{ bookings : places
  rooms ||--o{ bookings : holds
  </pre><script>alert('xss')</script>
```

### 1 · The booking cluster <script>alert(1)</script>

`bookings` is the hinge. Every other table hangs off it.

- `users` owns the booking
- `rooms` is what was held

### 2 · Money

`invoices` arrives late in the history, in its own act.

## The flows

### Guest books a room

| step | table |
| --- | --- |
| 1 | `rooms` read |
| 2 | `bookings` insert |

### Guest cancels

The row is soft-deleted, never removed.

## Table deep dive

### `bookings`

`state` is a string, not an enum, which is why two spellings of `cancelled` exist.

```sql
CREATE INDEX bookings_room_start ON bookings (room_id, starts_at);
```

### `invoices`

One index, on `booking_id`. Every report scans.

## Migration history

### Act 1 — The booking product (2021)

Rooms, users, bookings. Nothing else.

### Act 2 — Money (2022)

`invoices` appears, and never changes shape again.
