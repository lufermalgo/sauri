# sauri

Plataforma interna de inteligencia de reuniones comerciales de Summan.

## Qué hace

sauri captura reuniones de Google Meet (audio + video), las transcribe automáticamente en español y las asocia a la gestión comercial del equipo. Es una solución propia que se desarrolla por módulos incrementales.

## Módulos (roadmap)

| # | Módulo | Estado |
|---|--------|--------|
| 1 | Captura de reuniones | ✅ MVP implementado |
| 2 | Transcripción (ASR) | Pendiente |
| 3 | Identificación de hablantes | Pendiente |
| 4 | Notas e inteligencia | Pendiente |
| 5 | Integración con CRM (ClickUp) | Pendiente |
| 6 | Biblioteca y búsqueda | Pendiente |
| 7 | Analítica comercial | Pendiente |
| 8 | Administración | Pendiente |

## Stack tecnológico

- **Backend**: Python / FastAPI / SQLAlchemy / PostgreSQL
- **Extensión Chrome**: TypeScript / MV3 / React (Vite + CRXJS)
- **Frontend web**: TypeScript / React (Vite)
- **Motor ASR local**: faster-whisper (contenedor propio)
- **Infraestructura**: Docker Compose (PostgreSQL, MinIO, RabbitMQ, ASR engine)

## Desarrollo local

### Requisitos

- Docker Desktop (macOS)
- Node.js >= 20
- Python >= 3.11

### Levantar el backend

```bash
make up        # Levanta todo el stack Docker
make build     # Rebuild + levanta
make down      # Detiene todo
make logs      # Ver logs
make migrate   # Ejecutar migraciones de BD
```

### Extensión de Chrome

```bash
cd extension
npm install
npm run build
```

Luego cargar `extension/dist/` como extensión sin empaquetar en `chrome://extensions/` (modo desarrollador).

### Frontend web

```bash
cd frontend
npm install
npm run dev
```

## Estructura del proyecto

```
sauri/
├── backend/           # Python/FastAPI (API + workers)
├── extension/         # Chrome MV3 (captura de reuniones)
├── frontend/          # React SPA (consulta de reuniones)
├── packages/          # Tipos compartidos (@sauri/shared-types)
├── .spectra/specs/    # Especificaciones de módulos (Spectra)
├── docker-compose.yml # Stack local completo
├── Makefile           # Comandos de desarrollo
└── AGENTS.md          # Reglas y workflow del proyecto
```

## Workflow de desarrollo

Ver [AGENTS.md](./AGENTS.md) para las reglas completas. En resumen:

1. Cada módulo tiene un spec en `.spectra/specs/` (requirements/bugfix → design → tasks)
2. Cada tarea atómica → issue en GitHub asignado al milestone del módulo
3. Cada issue → branch → PR → merge a main
4. Milestones en GitHub reflejan el progreso del roadmap

## Seguridad

Ver [SECURITY.md](./SECURITY.md) para notas sobre TLS, cifrado y manejo de datos personales.
