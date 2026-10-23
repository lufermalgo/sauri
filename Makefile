# =============================================================================
# sauri - Makefile para desarrollo local
# =============================================================================

.PHONY: up down logs build clean migrate setup-hooks worktree worktree-rm check-english engines-install engines-up engines-down engines-status

SAURI_NATIVE_VENV ?= $(HOME)/.local/share/sauri/native-engines/venv
NATIVE_PYTHON311 ?= python3.11

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

## Instalar motores nativos en un venv fuera del repositorio (MLX + pyannote/MPS).
engines-install:
	mkdir -p "$(dir $(SAURI_NATIVE_VENV))" "$(HOME)/.config/sauri"
	@if [ ! -s "$(HOME)/.config/sauri/engine_token" ]; then umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$(HOME)/.config/sauri/engine_token"; fi
	@if [ ! -s "$(HOME)/.config/sauri/recording_capability_key" ]; then umask 077; python3 -c 'import secrets; print(secrets.token_hex(32))' > "$(HOME)/.config/sauri/recording_capability_key"; fi
	chmod 600 "$(HOME)/.config/sauri/engine_token" "$(HOME)/.config/sauri/recording_capability_key"
	$(NATIVE_PYTHON311) -m venv "$(SAURI_NATIVE_VENV)"
	"$(SAURI_NATIVE_VENV)/bin/python" -m pip install --upgrade pip
	"$(SAURI_NATIVE_VENV)/bin/python" -m pip install 'fastapi>=0.115' 'uvicorn[standard]>=0.30' 'pydantic>=2' 'boto3>=1.34' 'mlx-whisper' 'torch==2.5.1' 'torchaudio==2.5.1' 'pyannote.audio==3.3.2' 'huggingface_hub==0.24.7' 'matplotlib==3.9.2'

## Iniciar/detener/consultar los servidores nativos; cada uno usa su PID exacto.
engines-up:
	SAURI_NATIVE_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash _tools/native-engines.sh start all

engines-down:
	SAURI_NATIVE_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash _tools/native-engines.sh stop all

engines-status:
	SAURI_NATIVE_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash _tools/native-engines.sh status all

## Escanear todo el repo en busca de identificadores en español (Language_Regression_Check).
## Ver AGENTS.md para las reglas de idioma del código.
check-english:
	python3 _tools/check_english_only.py $$(git ls-files 'backend/**' 'extension/src/**' 'frontend/src/**' 'packages/shared-types/**')

## Levantar API, worker, PostgreSQL, MinIO y RabbitMQ; motores locales corren fuera de Compose
up:
	_tools/compose-bringup.sh

## Levantar con rebuild de imágenes
build:
	docker compose build
	_tools/compose-bringup.sh

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
