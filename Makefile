.DEFAULT_GOAL := help
.PHONY: help ollama-setup ollama-vision ollama-serve ollama-stop verify-local dev-local frontend install check

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1;36m%-14s\033[0m %s\n", $$1, $$2}'

ollama-setup: ## Install Ollama, start it, pull a model, wire .env (safe to re-run)
	@bash scripts/setup-ollama.sh

ollama-vision: ## Pull a local vision model + wire it (for Studio screenshot import)
	@bash scripts/setup-vision.sh

ollama-serve: ## Start the Ollama server in the background
	@curl -fsS --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1 \
		&& echo "Ollama already running" \
		|| ( mkdir -p .ollama-logs; nohup ollama serve >.ollama-logs/serve.log 2>&1 & echo "Ollama started" )

ollama-stop: ## Stop a background Ollama server
	@pkill -f "ollama serve" >/dev/null 2>&1 && echo "Ollama stopped" || echo "Ollama not running"

verify-local: ## Check Ollama + backend status
	@bash scripts/verify-local.sh

dev-local: ## Run the backend against the local Ollama model
	@bash scripts/run-local.sh

frontend: ## Run the Next.js frontend (separate terminal)
	@cd frontend && npm run dev

install: ## Set up .venv + install dev & backend deps + pre-commit hooks
	@test -d .venv || python3 -m venv .venv
	@.venv/bin/pip install --upgrade pip
	@.venv/bin/pip install -r requirements-dev.txt -r backend/requirements.txt
	@.venv/bin/pre-commit install

check: ## Run the full Python quality gate (ruff, format, mypy, pytest, pip-audit)
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.venv/bin/mypy backend/src
	.venv/bin/pytest
	.venv/bin/pip-audit
