# toy_repo: architecture

**Shape verdict:** A gateway in front of four services, with Postgres and Redis behind them.

toy_repo runs four services behind one gateway, with Auth0 and Stripe rented rather than run.

## The inventory

**Shape verdict:** A gateway in front of four services, with Postgres and Redis behind them.

```mermaid
graph LR
  gateway --> auth
  </pre><script>alert('xss')</script>
```

### 1 · Gateway <script>alert(1)</script> (run)

The front door. Declared in `docker-compose.yml:4`, one **replica**.

### 2 · Auth (rent)

Auth0 tenant, named by `AUTH0_DOMAIN`.

### 3 · Postgres (run)

One primary, no replica:

- migrations in `db/migrate/`
- pooled by pgbouncer

## Tech stack

### 1 · Gateway

Envoy 1.29, not nginx, despite the `nginx.conf` in the repo root.

```yaml
image: envoyproxy/envoy:v1.29
```

### 2 · Auth

Auth0, reached through `@auth0/nextjs-auth0` at `apps/web/lib/auth.ts:8`.

## The trace

### Hop 1 — Client to gateway

TLS terminates at Envoy; the JWT is not yet checked.

### Hop 2 — Gateway to auth

`apps/api/src/middleware/jwt.ts:22` verifies against Auth0's JWKS.

| variant | differs at |
| --- | --- |
| webhook | skips hop 2 |
