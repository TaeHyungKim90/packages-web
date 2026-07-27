.PHONY: help install install-backend install-frontend \
	backend frontend dev build preview env clean \
	lint lint-backend lint-frontend \
	test test-backend test-frontend check

BACKEND_DIR := backend
FRONTEND_DIR := frontend
BACKEND_PORT ?= 8000

.DEFAULT_GOAL := help

help:
	@echo ""
	@echo "  packages-web Make targets"
	@echo ""
	@echo "  make install          Install backend + frontend dependencies"
	@echo "  make install-backend  uv sync (backend)"
	@echo "  make install-frontend npm install (frontend)"
	@echo "  make env              Copy .env.example -> .env if missing"
	@echo "  make backend          Run FastAPI (port $(BACKEND_PORT))"
	@echo "  make frontend         Run Vite dev server (port 5173)"
	@echo "  make dev              Run backend + frontend in parallel"
	@echo "  make lint             Lint backend + frontend"
	@echo "  make lint-backend     ruff check"
	@echo "  make lint-frontend    eslint + tsc"
	@echo "  make test             Test backend + frontend"
	@echo "  make test-backend     pytest"
	@echo "  make test-frontend    vitest"
	@echo "  make check            lint + test"
	@echo "  make build            Build frontend for production"
	@echo "  make preview          Preview production frontend build"
	@echo "  make clean            Remove frontend build output"
	@echo ""
	@echo "  BACKEND_PORT=$(BACKEND_PORT)  (override: make backend BACKEND_PORT=8003)"
	@echo ""

env:
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env"; else echo ".env already exists"; fi

install: install-backend install-frontend

install-backend:
	cd $(BACKEND_DIR) && uv sync

install-frontend:
	cd $(FRONTEND_DIR) && npm install

backend:
	cd $(BACKEND_DIR) && uv run uvicorn main:app --reload --port $(BACKEND_PORT)

frontend:
	cd $(FRONTEND_DIR) && npm run dev

dev:
	$(MAKE) -j2 backend frontend

lint: lint-backend lint-frontend

lint-backend:
	cd $(BACKEND_DIR) && uv run ruff check .

lint-frontend:
	cd $(FRONTEND_DIR) && npm run lint

test: test-backend test-frontend

test-backend:
	cd $(BACKEND_DIR) && uv run pytest

test-frontend:
	cd $(FRONTEND_DIR) && npm test

check: lint test

build:
	cd $(FRONTEND_DIR) && npm run build

preview:
	cd $(FRONTEND_DIR) && npm run preview

clean:
	rm -rf $(FRONTEND_DIR)/dist
