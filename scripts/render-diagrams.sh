#!/usr/bin/env sh
set -eu

plantuml_jar=${PLANTUML_JAR:-/tmp/plantuml.jar}

if [ ! -f "$plantuml_jar" ]; then
  echo "PlantUML JAR not found: $plantuml_jar" >&2
  exit 1
fi

mkdir -p docs/diagrams
find docs/diagrams -maxdepth 1 -type f -name '*.png' -delete

java -Djava.awt.headless=true -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8 \
  -jar "$plantuml_jar" -charset UTF-8 -tpng -o diagrams \
  docs/use-case.puml docs/class.puml docs/erd.puml docs/ml-service-domain.puml \
  docs/ml-service-erd.puml docs/sequence-*.puml

java -Djava.awt.headless=true -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8 \
  -jar "$plantuml_jar" -charset UTF-8 -tpng -o ../diagrams \
  docs/plantuml/*.puml
