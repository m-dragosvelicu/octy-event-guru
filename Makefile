.PHONY: test-unit stack-up stack-down test-integration test-all

test-unit:
	pytest -m "not integration" -q

stack-up:
	docker compose -f docker-compose.test.yml up -d --wait

stack-down:
	docker compose -f docker-compose.test.yml down -v

test-integration:
	pytest -m "integration" -q

test-all: stack-up test-unit test-integration stack-down
