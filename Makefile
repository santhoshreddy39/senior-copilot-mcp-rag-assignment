.PHONY: setup run down test test-unit test-integration test-e2e coverage lint ingest \
        simulator backend frontend mcp-server-standalone

setup:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements-dev.txt

run:
	docker compose up --build

down:
	docker compose down

# --- Run each service locally without Docker (three separate terminals) ---
simulator:
	. .venv/bin/activate && ALARM_API_TOKEN=demo-token uvicorn apps.backend.simulator.main:app --port 8000

backend:
	. .venv/bin/activate && ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token \
		uvicorn apps.backend.main:app --port 8100

frontend:
	. .venv/bin/activate && BACKEND_URL=http://localhost:8100 streamlit run apps/frontend/app.py

# The MCP server can be started completely independently of the copilot backend,
# per the assignment's "MCP server runs independently" requirement.
mcp-server-standalone:
	. .venv/bin/activate && ALARM_API_BASE_URL=http://localhost:8000 ALARM_API_TOKEN=demo-token \
		python mcp-servers/alarm-management/server.py

ingest:
	. .venv/bin/activate && python scripts/ingest_documents.py

test:
	. .venv/bin/activate && pytest -q

test-unit:
	. .venv/bin/activate && pytest tests/unit rag/tests -q

test-integration:
	. .venv/bin/activate && pytest tests/integration -q

test-e2e:
	. .venv/bin/activate && pytest tests/e2e -q

coverage:
	. .venv/bin/activate && pytest --cov=apps --cov=connectors --cov=rag \
		--cov=mcp-servers/alarm-management --cov-report=term-missing --cov-report=html

lint:
	. .venv/bin/activate && ruff check . && ruff format --check .
