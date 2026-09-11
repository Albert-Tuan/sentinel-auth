#!/usr/bin/env python3
"""Generate diagrams using PlantUML public server."""
import plantuml
import os
from pathlib import Path

BASE = Path("/run/media/thaus/Lab/1_Project/sentinel-auth/sentinel-auth/docs/diagrams")

defs = [
    ("wf1_login.uml", "fig_wf1_login.png"),
    ("wf2_detection.uml", "fig_wf2_detection.png"),
    ("wf3_soc.uml", "fig_wf3_soc_alerts.png"),
    ("architecture.uml", "fig_architecture_overview.png"),
]

puml = plantuml.PlantUML("http://www.plantuml.com/plantuml")

for src_name, out_name in defs:
    src = BASE / src_name
    out = BASE / out_name
    print(f"Generating {out_name}...")
    try:
        puml.processes_file(str(src), str(out))
        size = os.path.getsize(out)
        print(f"  ✓ {out_name} ({size:,} bytes)")
    except Exception as e:
        print(f"  ✗ Error: {e}")
