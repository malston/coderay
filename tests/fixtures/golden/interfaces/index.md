# toy_repo: interfaces

Ninety-one endpoints, and two thirds of them are booking.

toy_repo is a booking API with a thin payments wing and almost no admin surface.

## Feature menu

### Booking <script>alert(1)</script> (42)

The biggest surface by far. `config/routes.rb:88` maps **42** paths.

- `POST /api/book` creates a hold
- `DELETE /api/book/:id` releases it

### Payments (18)

Stripe-backed, all under `pages/api/pay*`.

### Auth (6)

Session cookies, no bearer tokens.

## The tour

### Start at booking

It is where the product's idea lives.

### Then payments

Everything else exists to make this work.

## Action flows

### Guest books a room

| lane | step |
| --- | --- |
| web | `POST /api/book` |
| worker | holds inventory |

### Guest cancels

The hold is released, then Stripe is refunded.

## Endpoint sequence

```mermaid
sequenceDiagram
  client->>api: POST /api/book
  </pre><script>alert('xss')</script>
```

The hold is written before Stripe is called, so a failed charge leaves a row to reap.
