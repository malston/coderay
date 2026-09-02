# toy_repo: backend

_Core endpoint: POST /json/messages_

toy_repo is a small Django service with a hand-rolled REST dispatcher and a two-layer middleware stack.

## The pipeline

```mermaid
flowchart LR
  route --> mw
  </pre><script>alert('xss')</script>
```

### Route <script>alert(1)</script>

One `urls.py` maps **4** paths. See `app/urls.py:12`.

### Middleware

Two layers, both custom:

- auth
- rate limiting

### Handler

11 views under `app/views/`.

## The code

### Route — novel

A `rest_path` wrapper folds method dispatch into the URL table.

```python
def rest_path(route, **handlers):
    return path(route, rest_dispatch(**handlers))
```

### Middleware — standard

Stock Django middleware, nothing to read.

## The trace

**Endpoint:** POST /json/messages

### 1. Route

`app/urls.py:44` matches the path.

### 2. Handler

`app/views/message.py:88` validates, then calls the service.

| field | required |
| --- | --- |
| `content` | yes |
