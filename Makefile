.PHONY: verify-v2

verify-v2:
	docker compose -f docker-compose.v2.yaml run --rm --build test
