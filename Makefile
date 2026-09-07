REPO_ROOT := $(abspath .)
PYTHON ?= $(if $(wildcard .venv/bin/python),$(REPO_ROOT)/.venv/bin/python,python3)
SERVICES := core-app detection-engine ml-service

.PHONY: check test compose-config

check:
	"$(PYTHON)" -m compileall -q $(SERVICES)

test:
	@for service in $(SERVICES); do \
		(cd $$service && "$(PYTHON)" -m pytest -q); \
	done

compose-config:
	docker compose config --quiet
