# Bugfix Document Format

## Document Structure

```
# Bugfix — [Title]

## Descripción del Bug
## Pasos para Reproducir
## Comportamiento Actual (Defecto)
## Comportamiento Esperado (Correcto)
## Comportamiento Sin Cambios (Prevención de Regresiones)
## Restricciones del Fix
## Criterios de Aceptación
```

---

## Section: Descripción del Bug

1–2 sentences. What is broken and where. Enough for a reader to immediately understand the impact.

```markdown
## Descripción del Bug

La pantalla de login redirige a `/404` después de completar el flujo OAuth 
en Safari en iOS 17. Los usuarios en Chrome no experimentan este problema.
```

---

## Section: Pasos para Reproducir

Numbered steps, specific enough to write an automated test from them.

```markdown
## Pasos para Reproducir

1. Abrir la aplicación en Safari / iOS 17
2. Hacer click en "Iniciar sesión con Google"
3. Completar el flujo OAuth en la ventana popup
4. Observar que la aplicación redirige a `/404` en lugar de `/dashboard`

**Entorno:** iOS 17.4, Safari 17, producción y staging
**Frecuencia:** 100% reproducible en el entorno descrito
```

---

## Section: Comportamiento Actual (Defecto)

Use this EARS pattern — **no SHALL**, this is the defect:
```
WHEN [condition] THEN the system [incorrect behavior]
```

```markdown
## Comportamiento Actual (Defecto)

WHEN a user completes OAuth flow in Safari on iOS 17,  
THEN the system redirects to `/404` instead of the intended post-login route.

WHEN the OAuth callback is received on iOS Safari,  
THEN the `session_state` parameter is missing from the redirect URL.
```

---

## Section: Comportamiento Esperado (Correcto)

Use this EARS pattern — **with SHALL**:
```
WHEN [condition] THEN the system SHALL [correct behavior]
```

```markdown
## Comportamiento Esperado (Correcto)

WHEN a user completes OAuth flow in any supported browser,  
THEN the system SHALL redirect to `/dashboard` with an active session.

WHEN the OAuth callback is received,  
THEN the system SHALL handle the absence of optional `session_state` 
parameter gracefully without throwing a routing error.
```

---

## Section: Comportamiento Sin Cambios (Prevención de Regresiones)

**This is the most important section. Never leave it empty.**

Use this EARS pattern:
```
WHEN [condition] THEN the system SHALL CONTINUE TO [existing correct behavior]
```

Think about every behavior in the same code path that must not change:

```markdown
## Comportamiento Sin Cambios (Prevención de Regresiones)

WHEN a user completes OAuth flow in Chrome (any platform),  
THEN the system SHALL CONTINUE TO redirect to `/dashboard` correctly.

WHEN a user completes OAuth flow in Firefox,  
THEN the system SHALL CONTINUE TO redirect to `/dashboard` correctly.

WHEN OAuth fails due to user denial,  
THEN the system SHALL CONTINUE TO redirect to the login page with an error message.

WHEN a session token expires,  
THEN the system SHALL CONTINUE TO prompt re-authentication without data loss.

WHEN an authenticated user accesses a protected route directly,  
THEN the system SHALL CONTINUE TO serve the route without triggering the OAuth flow.
```

**Tips for completeness:**
- Walk through the code path from entry to exit
- List every branch the fix touches that must keep working
- Include adjacent features that share the same callback handler or session logic
- If uncertain, err on the side of listing more rather than fewer

---

## Section: Restricciones del Fix

Real technical constraints on the fix. Be specific.

```markdown
## Restricciones del Fix

- Must not change the public interface of `handleOAuthCallback()` — it's called 
  from three other places
- Must remain compatible with the existing session JWT format (no schema changes)
- Must not add a new dependency — the fix must use native platform APIs
- Safari 16 (iOS 16) must continue to work exactly as it does today
```

**Not constraints:** "minimal change", "don't break things", "be careful"

---

## Section: Criterios de Aceptación

Verifiable statements that confirm:
1. The bug is fixed
2. No regressions were introduced

```markdown
## Criterios de Aceptación

1. WHEN a user completes OAuth in Safari on iOS 17, THE SYSTEM SHALL redirect 
   to `/dashboard` with an active authenticated session.

2. WHEN the OAuth callback URL does not include `session_state`, THE SYSTEM SHALL 
   complete authentication successfully without throwing a routing error.

3. FOR ALL supported browsers (Chrome, Firefox, Safari on macOS and iOS), 
   the OAuth login flow SHALL complete successfully and redirect to `/dashboard`.

4. WHEN OAuth fails due to user denial or error, THE SYSTEM SHALL CONTINUE TO 
   redirect to login with the appropriate error message in all browsers.
```

---

## Worked Example (abbreviated)

```markdown
# Bugfix — Login Redirect 404 in Safari iOS 17

## Descripción del Bug
La pantalla de login redirige a `/404` después del OAuth en Safari iOS 17.

## Pasos para Reproducir
1. Abrir en Safari / iOS 17
2. Click "Iniciar sesión con Google"
3. Completar OAuth flow
4. Observar redirección incorrecta

## Comportamiento Actual (Defecto)
WHEN user completes OAuth in Safari iOS 17,
THEN the system redirects to `/404`.

## Comportamiento Esperado (Correcto)
WHEN user completes OAuth in any supported browser,
THEN the system SHALL redirect to `/dashboard` with active session.

## Comportamiento Sin Cambios (Prevención de Regresiones)
WHEN user completes OAuth in Chrome,
THEN the system SHALL CONTINUE TO redirect to `/dashboard` correctly.

WHEN OAuth fails due to user denial,
THEN the system SHALL CONTINUE TO show the error message on login.

## Restricciones del Fix
- Must not change public interface of `handleOAuthCallback()`
- Must not add new dependencies

## Criterios de Aceptación
1. WHEN completing OAuth in Safari iOS 17, THE SYSTEM SHALL redirect to `/dashboard`.
2. FOR ALL supported browsers, the OAuth login flow SHALL complete successfully.
```
