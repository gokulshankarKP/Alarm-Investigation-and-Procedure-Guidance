# Developer shortcuts. On Windows without make, run the commands shown here directly
# (or use: python scripts/run_local.py).
PY ?= python
export PYTHONPATH := .:apps/alarm-api-simulator:apps/backend:apps/frontend:mcp-servers/alarm-management
SRC := apps mcp-servers connectors rag shared tests scripts

.PHONY: install lint format typecheck test test-unit test-integration test-e2e coverage audit ingest \
        run-api run-mcp run-mcp-stdio run-backend run-ui run-all postman screenshots diagram up down logs

install:            ## install runtime + dev dependencies
	$(PY) -m pip install -r requirements-dev.txt

lint:               ## ruff lint + format check
	$(PY) -m ruff check $(SRC)
	$(PY) -m ruff format --check $(SRC)

format:
	$(PY) -m ruff format $(SRC)
	$(PY) -m ruff check $(SRC) --fix

typecheck:
	$(PY) -m mypy apps/alarm-api-simulator/alarm_api_sim apps/backend/copilot mcp-servers/alarm-management/alarm_mcp connectors rag shared --exclude rag/tests

test:               ## full suite (pgvector tests skip without a database)
	$(PY) -m pytest

test-unit:
	$(PY) -m pytest tests/unit rag/tests

test-integration:
	$(PY) -m pytest tests/integration

test-e2e:
	$(PY) -m pytest tests/e2e

coverage:           ## test suite + coverage report in docs/coverage
	$(PY) -m pytest --cov --cov-report=term --cov-report=html:docs/coverage/html --cov-report=xml:docs/coverage/coverage.xml

audit:              ## dependency vulnerability scan
	$(PY) -m pip_audit -r requirements.txt

ingest:             ## chunk + embed + index the document corpus into pgvector
	$(PY) -m rag.ingestion

run-api:
	$(PY) -m alarm_api_sim --port 8000

run-mcp:            ## MCP server over streamable HTTP (http://127.0.0.1:9000/mcp)
	$(PY) -m alarm_mcp

run-mcp-stdio:      ## MCP server over stdio (MCP Inspector, desktop clients)
	$(PY) -m alarm_mcp --transport stdio

run-backend:
	$(PY) -m copilot

run-ui:
	$(PY) -m streamlit run apps/frontend/copilot_ui/app.py

run-all:            ## all services locally (Ctrl+C stops everything)
	$(PY) scripts/run_local.py

postman:            ## run the Postman contract collections against a running simulator (needs Node.js)
	npx --yes newman run test-data/postman/Alarm-API-Simulator.postman_collection.json
	npx --yes newman run test-data/postman/Alarm-API-Chaining.postman_collection.json

screenshots:        ## GUI screenshots into docs/screenshots (stack must be running)
	$(PY) scripts/capture_screenshots.py

diagram:
	$(PY) scripts/render_architecture_diagram.py

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f backend alarm-mcp
