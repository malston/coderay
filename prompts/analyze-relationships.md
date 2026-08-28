Given these abstractions from a codebase:

{abstractions}

Codebase:

{codebase}

Describe the key relationships between them. Simplify and exclude non important ones. Every abstraction must appear in at least one relationship.

For each:
- `from`: source abstraction name
- `to`: target abstraction name
- `label`: brief verb phrase (e.g. "manages", "uses", "notifies", "controls")

Respond in YAML, fenced:

```yaml
relationships:
  - from: "AbstractionA"
    to: "AbstractionB"
    label: "uses"
```
