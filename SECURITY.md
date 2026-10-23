# Security Notes — sauri

## TLS in Transit

TLS in transit is enforced at the reverse-proxy/load-balancer level in production deployments. All inter-service communication (API ↔ workers, API ↔ Motor_ASR cloud provider) uses encrypted channels (HTTPS/TLS).

In local development (Docker Compose), traffic between containers runs over the internal Docker network without TLS; this is acceptable because no data leaves the host machine.

## Encryption at Rest

Encryption at rest is enabled at the infrastructure layer:

- **PostgreSQL**: disk-level encryption enabled on the managed instance (GCP Cloud SQL / AWS RDS). In local development, data at rest is not encrypted (acceptable for dev).
- **MinIO / Object Storage (S3-compatible)**: server-side encryption (SSE) enabled on the bucket configuration. In production, this maps to GCP Cloud Storage (default encryption) or AWS S3 (SSE-S3 or SSE-KMS).

## Access Control

- All API endpoints that expose Grabaciones_De_Sesion or Transcripciones require JWT authentication.
- Access is restricted to Usuarios_Comerciales autorizados (claim `es_comercial = true`).
- Unauthorized access attempts are logged in the `RegistroDeAcceso` table.

## Data Classification

Audio, video, and transcription data are treated as personal data subject to Colombian data protection law (Ley 1581 de 2012). Retention policies ensure automatic deletion after the configured period expires.

## Native inference recording authorization

Native ASR and diarization requests require both the existing engine bearer token and an
`X-Sauri-Recording-Capability`. The backend worker signs the exact `audio_ref` and a 60-second
expiry with the independent key at `~/.config/sauri/recording_capability_key` (override with
`SAURI_RECORDING_CAPABILITY_KEY_FILE`). Engine handlers verify the signature and expiry before
object download or inference; a broad engine bearer alone cannot authorize an object. The key is
created by `make engines-install`, mode `0600`, mounted read-only into the Compose worker, and read
by host-native engines. Keep it separate from `engine_token`, restrict it to trusted worker/engine
processes, rotate it by replacing it on both sides and restarting them, and do not log capabilities.
Capabilities scope access to one exact object reference; this boundary assumes only the trusted
backend worker can mint them and does not replace application-level authorization at user-facing
API routes.
