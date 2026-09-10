# Render PlantUML diagrams

All diagram source is authoritative. Do not edit PNG files manually.

## Prerequisites

- Java 17+.
- PlantUML JAR. Set `PLANTUML_JAR` or use `/tmp/plantuml.jar`.

## Render

From the repository root:

```bash
PLANTUML_JAR=/tmp/plantuml.jar ./scripts/render-diagrams.sh
```

The script clears only generated PNGs in `docs/diagrams/`, then renders:

- `docs/use-case.puml`, `docs/class.puml`, `docs/erd.puml`
- `docs/ml-service-domain.puml`, `docs/ml-service-erd.puml`
- six `docs/sequence-*.puml` diagrams
- role-focused use-case diagrams in `docs/plantuml/`

Commit source `.puml` files. Commit generated PNGs only when the report submission requires them; regenerate them in CI/document build from the same source.
