# =============================================================================
# sauri - Makefile para desarrollo local
# =============================================================================

.PHONY: up down logs build clean migrate

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
