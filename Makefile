# =============================================================================
# sauri - Makefile para desarrollo local
# =============================================================================

.PHONY: up down logs build clean migrate setup-hooks worktree worktree-rm check-english engines-install engines-up engines-down engines-status

SAURI_NATIVE_VENV ?= $(HOME)/.local/share/sauri/native-engines/asr-venv
NATIVE_PYTHON311 ?= python3.11

## Instalar los git hooks compartidos (bloquean commit/push directo a main).
## Se ejecuta automáticamente con `npm install` en la raíz (script "prepare"),
## pero disponible aquí para quien solo trabaje en backend/ sin tocar npm.
setup-hooks:
	git config core.hooksPath .githooks
	@echo "core.hooksPath -> .githooks (ver AGENTS.md: Code changes and Git protection)"

## Crear un worktree + rama aislados para un spec/issue: make worktree BRANCH=feature/issue-12-desc
worktree:
	@test -n "$(BRANCH)" || (echo "Uso: make worktree BRANCH=feature/issue-12-desc" && exit 1)
	scripts/dev/new-worktree.sh $(BRANCH)

## Eliminar un worktree ya mergeado: make worktree-rm BRANCH=feature/issue-12-desc
worktree-rm:
	@test -n "$(BRANCH)" || (echo "Uso: make worktree-rm BRANCH=feature/issue-12-desc" && exit 1)
	scripts/dev/remove-worktree.sh $(BRANCH)

## Instalar motores nativos en un venv fuera del repositorio (whisper.cpp + Senko/CoreML).
engines-install:
	bash scripts/engines/ensure-native-engine-credentials.sh
	SAURI_ASR_VENV="$(SAURI_NATIVE_VENV)" NATIVE_PYTHON311="$(NATIVE_PYTHON311)" bash scripts/engines/install-asr-engine.sh
	NATIVE_PYTHON311="$(NATIVE_PYTHON311)" bash scripts/engines/install-diar-engine.sh

## Iniciar/detener/consultar los servidores nativos; cada uno usa su PID exacto.
engines-up:
	bash scripts/engines/ensure-native-engine-credentials.sh
	SAURI_ASR_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash scripts/engines/native-engines.sh start all

engines-down:
	SAURI_ASR_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash scripts/engines/native-engines.sh stop all

engines-status:
	SAURI_ASR_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash scripts/engines/native-engines.sh status all

## Escanear todo el repo en busca de identificadores en español (Language_Regression_Check).
## Ver AGENTS.md para las reglas de idioma del código.
check-english:
	python3 scripts/dev/check_english_only.py $$(git ls-files 'backend/**' 'extension/src/**' 'frontend/src/**' 'packages/shared-types/**')

## Levantar API, worker, PostgreSQL, MinIO y RabbitMQ; motores locales corren fuera de Compose
up:
	scripts/platform/compose-bringup.sh

## Levantar con rebuild de imágenes
build:
	docker compose build
	scripts/platform/compose-bringup.sh

## Ver logs de todos los servicios
logs:
	docker compose logs -f

## Detener todos los servicios
down:
	docker compose down

## Detener y eliminar volúmenes (datos locales)
clean:
	docker compose down -v

## Ejecutar migraciones de base de datos
migrate:
	docker compose exec api alembic upgrade head

# -----------------------------------------------------------------------------
# Extensión de Chrome
# -----------------------------------------------------------------------------
# Para cargar la extensión como "unpacked" en Chrome:
#   1. cd extension && npm run build
#   2. Abrir chrome://extensions
#   3. Activar "Modo desarrollador"
#   4. "Cargar extensión sin empaquetar" → seleccionar extension/dist
#
# La extensión apunta al endpoint de ingesta local: http://localhost:8000
# -----------------------------------------------------------------------------
