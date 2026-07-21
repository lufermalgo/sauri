# =============================================================================
# sauri - Makefile para desarrollo local
# =============================================================================

.PHONY: up down logs build clean migrate setup-hooks worktree worktree-rm check-english

## Instalar los git hooks compartidos (bloquean commit/push directo a main).
## Se ejecuta automáticamente con `npm install` en la raíz (script "prepare"),
## pero disponible aquí para quien solo trabaje en backend/ sin tocar npm.
setup-hooks:
	git config core.hooksPath .githooks
	@echo "core.hooksPath -> .githooks (ver AGENTS.md §6-7)"

## Crear un worktree + rama aislados para un spec/issue: make worktree BRANCH=feature/issue-12-desc
worktree:
	@test -n "$(BRANCH)" || (echo "Uso: make worktree BRANCH=feature/issue-12-desc" && exit 1)
	_tools/new-worktree.sh $(BRANCH)

## Eliminar un worktree ya mergeado: make worktree-rm BRANCH=feature/issue-12-desc
worktree-rm:
	@test -n "$(BRANCH)" || (echo "Uso: make worktree-rm BRANCH=feature/issue-12-desc" && exit 1)
	_tools/remove-worktree.sh $(BRANCH)

## Escanear todo el repo en busca de identificadores en español (Language_Regression_Check).
## Ver .spectra/specs/english-codebase-standard/
check-english:
	python3 _tools/check_english_only.py $$(git ls-files 'backend/**' 'extension/src/**' 'frontend/src/**' 'packages/shared-types/**')

## Levantar el stack completo (API, worker, PostgreSQL, MinIO, RabbitMQ, ASR engine)
up:
	docker compose up -d

## Levantar con rebuild de imágenes
build:
	docker compose up -d --build

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
