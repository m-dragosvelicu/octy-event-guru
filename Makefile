.PHONY: test-unit stack-up stack-down test-integration test-e2e test-all

test-unit:
	pytest -m "not integration and not e2e" -q

stack-up:
	docker compose -f docker-compose.test.yml up -d --wait

stack-down:
	docker compose -f docker-compose.test.yml down -v

test-integration:
	pytest -m "integration" -q

test-e2e:
	pytest tests/integration/test_e2e_bucharest.py -q

test-all: stack-up test-unit test-integration stack-down
