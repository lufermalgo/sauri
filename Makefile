# =============================================================================
# sauri - Makefile para desarrollo local
# =============================================================================

.PHONY: up down logs build clean migrate setup-hooks worktree worktree-rm check-english test-scripts test-pg engines-install engines-up engines-down engines-status package package-clean

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

## Pruebas de los scripts (compose-bringup, validacion de plataforma, admision de pipeline).
test-scripts:
	cd backend && uv run --extra dev python -m pytest ../scripts/tests -q
	scripts/tests/test_pg_disposable.sh

## Ejecutar las pruebas PostgreSQL contra un clúster local desechable.
test-pg:
	scripts/tests/pg-disposable.sh -- sh -c 'cd backend && uv run --extra dev python -m pytest tests/infra/test_queue_postgres.py -q'

## Instalar motores nativos en un venv fuera del repositorio (whisper.cpp + Senko/CoreML + Parakeet si hay Swift).
engines-install:
	bash scripts/engines/ensure-native-engine-credentials.sh
	SAURI_ASR_VENV="$(SAURI_NATIVE_VENV)" NATIVE_PYTHON311="$(NATIVE_PYTHON311)" bash scripts/engines/install-asr-engine.sh
	NATIVE_PYTHON311="$(NATIVE_PYTHON311)" bash scripts/engines/install-diar-engine.sh
	bash scripts/engines/install-llm-engine.sh
	bash scripts/engines/install-host-engine.sh
	@# Parakeet (fast transcription) needs the Swift toolchain; without it (exit 3) Whisper keeps transcribing.
	SAURI_ASR_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash scripts/engines/install-parakeet-engine.sh || [ $$? -eq 3 ]

## Iniciar/detener/consultar los servidores nativos; cada uno usa su PID exacto.
engines-up:
	bash scripts/engines/ensure-native-engine-credentials.sh
	SAURI_ASR_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash scripts/engines/native-engines.sh start all

engines-down:
	bash scripts/platform/deploy-guard.sh "stop the native engines"
	SAURI_ASR_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash scripts/engines/native-engines.sh stop all

engines-status:
	SAURI_ASR_ENGINE_PYTHON="$(SAURI_NATIVE_VENV)/bin/python" bash scripts/engines/native-engines.sh status all

## Escanear todo el repo en busca de identificadores en español (Language_Regression_Check).
## Ver AGENTS.md para las reglas de idioma del código.
check-english:
	python3 scripts/dev/check_english_only.py $$(git ls-files 'backend/**' 'extension/src/**' 'frontend/src/**' 'packages/shared-types/**')

## Levantar API, worker, PostgreSQL, MinIO y RabbitMQ; motores locales corren fuera de Compose.
## Este y los demás objetivos que reinician servicios se niegan si hay reuniones procesándose: FORCE=1 lo omite.
up:
	bash scripts/platform/deploy-guard.sh "recreate the API and worker"
	scripts/platform/compose-bringup.sh

## Llave privada de la cola: se genera una vez en ~/.config/sauri y nunca se imprime ni se versiona.
## Compose la exige en cualquier comando (build, logs, down), así que se carga desde su archivo.
WITH_QUEUE_KEY = QUEUE_MESSAGE_SIGNING_KEY="$$(cat $(HOME)/.config/sauri/queue_signing_key 2>/dev/null)"

## Levantar con rebuild de imágenes
build:
	bash scripts/platform/deploy-guard.sh "rebuild and recreate the API and worker"
	bash scripts/engines/ensure-native-engine-credentials.sh
	$(WITH_QUEUE_KEY) docker compose build
	scripts/platform/compose-bringup.sh

## Ver logs de todos los servicios
logs:
	$(WITH_QUEUE_KEY) docker compose logs -f

## Detener todos los servicios
down:
	bash scripts/platform/deploy-guard.sh "stop all services"
	$(WITH_QUEUE_KEY) docker compose down

## Detener y eliminar volúmenes (datos locales)
clean:
	bash scripts/platform/deploy-guard.sh "stop all services and delete local data"
	$(WITH_QUEUE_KEY) docker compose down -v

## Ejecutar migraciones de base de datos
migrate:
	docker compose exec api alembic upgrade head

# -----------------------------------------------------------------------------
# Desktop app (design D1, D9, D10)
# -----------------------------------------------------------------------------
## Installer: desktop/out/Sauri-<version>-mac-arm64.{dmg,zip} plus .sha256, ad-hoc signed.
## Reuses the runtime in RUNTIME_DIR when it exists, otherwise builds it there (slow). The speaker runtime
## (components/diar) is left out: it is downloaded separately. Intermediate output (.stage, unpacked app) is removed.
RUNTIME_DIR ?= $(HOME)/Library/Caches/sauri-runtime-build/runtime-current
DESKTOP_OUT := desktop/out

package:
	@test -f "$(RUNTIME_DIR)/runtime-manifest.json" || SAURI_RUNTIME_DIR="$(RUNTIME_DIR)" bash desktop/scripts/build-runtime.sh
	VITE_API_BASE_URL= npm run build -w frontend
	npm run build -w desktop
	node desktop/scripts/stage.mjs --runtime "$(RUNTIME_DIR)" --portal frontend/dist
	rm -rf $(DESKTOP_OUT)
	cd desktop && npx --no-install electron-builder --mac --arm64 --config electron-builder.json --publish never
	node desktop/scripts/verify-package.mjs $(DESKTOP_OUT)/mac-arm64/Sauri.app "$(RUNTIME_DIR)"
	cd $(DESKTOP_OUT) && for f in Sauri-*-mac-arm64.dmg Sauri-*-mac-arm64.zip; do shasum -a 256 "$$f" > "$$f.sha256"; done
	rm -rf desktop/.stage $(DESKTOP_OUT)/mac-arm64 $(DESKTOP_OUT)/.icon-icns $(DESKTOP_OUT)/builder-*.yml $(DESKTOP_OUT)/*.blockmap
	@ls -l $(DESKTOP_OUT)

## Remove the package and every intermediate output (the runtime in RUNTIME_DIR is kept).
package-clean:
	rm -rf $(DESKTOP_OUT) desktop/.stage desktop/dist

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
