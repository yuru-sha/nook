.PHONY: help setup setup-dev lint format mypy docker-base docker-collector docker-viewer docker-all docker-run cdk-deploy clean

# デフォルトターゲット
.DEFAULT_GOAL := help

# 環境変数
PYTHON := python
PIP := pip

# ヘルプメッセージの表示
help:
	@echo "Available commands:"
	@echo "  make clean          - Clean up temporary files and caches"
	@echo "  make setup          - Install production dependencies"
	@echo "  make setup-dev      - Install development dependencies"
	@echo "  make lint          - Run static code analysis"
	@echo "  make format        - Format code"
	@echo "  make mypy          - Run type checking"
	@echo "  make docker-base    - Build base Docker image"
	@echo "  make docker-collector - Build and run Collector container"
	@echo "  make docker-viewer   - Build and run Viewer container"
	@echo "  make docker-all     - Build and run all containers"
	@echo "  make docker-run     - Run all containers without rebuilding"
	@echo "  make cdk-deploy    - Deploy using CDK"

# セットアップ
setup:
	uv $(PIP) install -r requirements.txt

# 開発環境のセットアップ
setup-dev:
	uv $(PIP) install -r requirements.txt -r requirements-dev.txt

# リンター実行
lint:
	uv run ruff check --statistics .

# フォーマッター実行
format:
	uv run ruff format .
	uv run ruff check --fix .

# 型チェック実行
mypy:
	uv run mypy . || true

clean:
	@echo "Cleaning temporary files and caches..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.py[cod]" -delete
	find . -type f -name "*.so" -delete
	find . -type f -name "*.pyi" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type f -name ".coverage" -delete
	find . -type f -name "coverage.xml" -delete
	find . -type d -name "coverage_html" -exec rm -rf {} +
	@echo "Cleaning completed."

# Docker commands
docker-base:
	docker build -t nook-base:latest ./docker/base

docker-collector: docker-base
	docker compose build nook-collector
	docker compose up -d nook-collector

docker-viewer: docker-base
	docker compose build nook-viewer
	docker compose up -d nook-viewer

docker-all: docker-base
	docker compose up --build -d

docker-run:
	docker compose up -d

# CDKデプロイ
cdk-deploy:
	cp nook/lambda/common/requirements.txt nook/lambda/tech_feed/requirements-common.txt
	cp nook/lambda/common/python/gemini_client.py nook/lambda/tech_feed/gemini_client.py
	cdk deploy
	rm nook/lambda/tech_feed/requirements-common.txt
	rm nook/lambda/tech_feed/gemini_client.py
