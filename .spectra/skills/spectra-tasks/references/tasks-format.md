# Tasks Document Format

## Document Structure

```
# Plan de Implementación — [Title]

## Resumen de Fases
## Fase 1: [Foundation]
## Fase 2: [Core Implementation]
## Fase 3: [Testing & Validation]
## Fase 4: [Integration]
```

---

## Section: Resumen de Fases

A compact overview so a reader can orient before diving into tasks.

```markdown
## Resumen de Fases

| Fase | Descripción | Tareas | Dependencias |
|------|-------------|--------|--------------|
| 1 | Infraestructura base (tokens CSS) | 1.1 – 1.4 | Ninguna |
| 2 | Utilidad de contraste | 2.1 – 2.3 | Fase 1 |
| 3 | Tests unitarios y property-based | 3.1 – 3.5 | Fase 2 |
| 4 | Migración de componentes | 4.1 – 4.3 | Fase 1 |
```

---

## Section: Tasks

Each phase is a `##` header. Each task is a `###` header with a number (e.g., `### Tarea 1.1`).

### Task anatomy

Every task has exactly these parts:

```markdown
### Tarea 1.1: Descriptive title

**Archivo:** `path/to/file.ts`
**Acción:** What to do — specific enough to execute without reading anything else.

**Criterio de Completado:**
Exact observable condition. Running a command, seeing a UI state, a test passing.

**Dependencias:** Task 0.X (or "Ninguna")
```

**Rule:** If the "Acción" field requires reading another document to understand what to do, it's not specific enough.

---

## Complete Example

```markdown
# Plan de Implementación — Sistema de Contraste de Color

## Resumen de Fases

| Fase | Descripción | Tareas | Dependencias |
|------|-------------|--------|--------------|
| 1 | Tokens CSS base | 1.1 – 1.3 | Ninguna |
| 2 | Utilidad de contraste | 2.1 – 2.2 | Fase 1 |
| 3 | Tests | 3.1 – 3.4 | Fase 2 |
| 4 | Migración de componentes | 4.1 – 4.2 | Fase 1 |

---

## Fase 1: Tokens CSS Base

### Tarea 1.1: Actualizar tokens de fondo en modo claro

**Archivo:** `frontend/src/style/index.css`
**Acción:** En el bloque `:root`, actualizar los siguientes tokens con sus valores exactos:
```css
--bg-base: #f8fafc;
--bg-surface: #ffffff;
--bg-elevated: #f1f5f9;
--bg-overlay: #e2e8f0;
```

**Criterio de Completado:**
Abrir la aplicación en modo claro y verificar que el fondo principal es `#f8fafc` (blanco ligeramente azulado, no blanco puro).

**Dependencias:** Ninguna

---

### Tarea 1.2: Actualizar tokens de fondo en modo oscuro

**Archivo:** `frontend/src/style/index.css`
**Acción:** En el bloque `[data-theme='dark']`, actualizar:
```css
--bg-base: #0f172a;
--bg-surface: #1e293b;
--bg-elevated: #334155;
--bg-overlay: #475569;
```

**Criterio de Completado:**
Activar modo oscuro con el toggle y verificar que el fondo principal cambia a `#0f172a` (azul muy oscuro, distinguible del negro puro).

**Dependencias:** Tarea 1.1

---

### Tarea 1.3: Actualizar tokens de texto (ambos modos)

**Archivo:** `frontend/src/style/index.css`
**Acción:** En `:root`:
```css
--text-primary: #111827;
--text-secondary: #374151;
--text-muted: #6b7280;
--text-on-brand: #ffffff;
```
En `[data-theme='dark']`:
```css
--text-primary: #f1f5f9;
--text-secondary: #d1d5db;
--text-muted: #9ca3af;
--text-on-brand: #ffffff;
```

**Criterio de Completado:**
El texto de navegación principal es legible en ambos modos sin parecer gris al leerlo en luz directa.

**Dependencias:** Ninguna

---

## Fase 2: Utilidad de Contraste

### Tarea 2.1: Crear `contrast-utils.ts`

**Archivo:** `frontend/src/utils/contrast-utils.ts` (crear si no existe)
**Acción:** Implementar las siguientes funciones exportadas:

```typescript
/** Parsea #RGB o #RRGGBB a [r, g, b] normalizados (0-1). Lanza si inválido. */
export function parseHex(hex: string): [number, number, number] {
  // validar que empiece con #
  // aceptar #RGB (expandir a #RRGGBB) y #RRGGBB
  // devolver [r/255, g/255, b/255]
}

/** Luminancia relativa WCAG 2.1 */
export function relativeLuminance(r: number, g: number, b: number): number {
  // aplicar gamma inverse sRGB (c <= 0.04045 ? c/12.92 : ((c+0.055)/1.055)^2.4)
  // devolver 0.2126*R + 0.7152*G + 0.0722*B
}

/** Ratio de contraste. Siempre >= 1. */
export function contrastRatio(hex1: string, hex2: string): number {
  // L1 = max(lum1, lum2), L2 = min
  // devolver (L1 + 0.05) / (L2 + 0.05)
}

/** Verifica si el par cumple el umbral */
export function meetsContrast(fg: string, bg: string, threshold: number): boolean {
  return contrastRatio(fg, bg) >= threshold;
}
```

**Criterio de Completado:**
`contrastRatio('#000000', '#ffffff')` devuelve `21` (o muy cercano). `contrastRatio('#ffffff', '#ffffff')` devuelve `1`.

**Dependencias:** Ninguna

---

### Tarea 2.2: Verificar manejo de errores en `parseHex`

**Archivo:** `frontend/src/utils/contrast-utils.ts`
**Acción:** Asegurarse de que `parseHex` lanza `Error('Invalid hex color format')` para:
- Strings sin `#` inicial
- Longitudes distintas de 4 (RGB) o 7 (RRGGBB) caracteres
- Caracteres no hexadecimales

**Criterio de Completado:**
`parseHex('invalid')` lanza, `parseHex('#gg0000')` lanza, `parseHex('#fff')` devuelve `[1, 1, 1]`.

**Dependencias:** Tarea 2.1

---

## Fase 3: Tests

### Tarea 3.1: Crear test unitario para `contrast-utils.ts`

**Archivo:** `frontend/src/__tests__/contrast-utils.test.ts` (crear)
**Acción:** Escribir tests unitarios para los casos específicos de tokens:

```typescript
describe('contrastRatio', () => {
  it('negro sobre blanco devuelve 21', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 1);
  });
  it('color idéntico devuelve 1', () => {
    expect(contrastRatio('#4f46e5', '#4f46e5')).toBe(1);
  });
  it('es simétrico', () => {
    const a = contrastRatio('#111827', '#f1f5f9');
    const b = contrastRatio('#f1f5f9', '#111827');
    expect(a).toBeCloseTo(b, 10);
  });
});

describe('meetsContrast', () => {
  it('--text-primary sobre --bg-base modo claro cumple WCAG AA texto (4.5)', () => {
    expect(meetsContrast('#111827', '#f8fafc', 4.5)).toBe(true);
  });
  it('--text-primary sobre --bg-base modo oscuro cumple WCAG AA texto (4.5)', () => {
    expect(meetsContrast('#f1f5f9', '#0f172a', 4.5)).toBe(true);
  });
});
```

**Criterio de Completado:**
`cd frontend && npx vitest --run contrast-utils.test` pasa todos los tests.

**Dependencias:** Tarea 2.1, Tarea 2.2

---

### Tarea 3.2: Crear property-based tests para `contrast-utils.ts`

**Archivo:** `frontend/src/__tests__/properties/contrast.property.test.ts` (crear)
**Acción:** Instalar `fast-check` si no está (`npm install --save-dev fast-check`) e implementar:

```typescript
import * as fc from 'fast-check';
import { contrastRatio, parseHex } from '../../utils/contrast-utils';

describe('Propiedad 1: simetría y cotas', () => {
  it('contrastRatio(a, b) === contrastRatio(b, a)', () => {
    fc.assert(fc.property(
      fc.hexaString({ minLength: 6, maxLength: 6 }).map(s => '#' + s),
      fc.hexaString({ minLength: 6, maxLength: 6 }).map(s => '#' + s),
      (a, b) => {
        expect(contrastRatio(a, b)).toBeCloseTo(contrastRatio(b, a), 10);
      }
    ));
  });

  it('contrastRatio >= 1 siempre', () => {
    fc.assert(fc.property(
      fc.hexaString({ minLength: 6, maxLength: 6 }).map(s => '#' + s),
      fc.hexaString({ minLength: 6, maxLength: 6 }).map(s => '#' + s),
      (a, b) => {
        expect(contrastRatio(a, b)).toBeGreaterThanOrEqual(1);
      }
    ));
  });
});

describe('Propiedad 2: round-trip de parseHex', () => {
  it('parseHex reconstruye los valores normalizados correctamente', () => {
    fc.assert(fc.property(
      fc.integer({ min: 0, max: 255 }),
      fc.integer({ min: 0, max: 255 }),
      fc.integer({ min: 0, max: 255 }),
      (r, g, b) => {
        const hex = '#' + [r, g, b].map(n => n.toString(16).padStart(2, '0')).join('');
        const [pr, pg, pb] = parseHex(hex);
        expect(pr).toBeCloseTo(r / 255, 10);
        expect(pg).toBeCloseTo(g / 255, 10);
        expect(pb).toBeCloseTo(b / 255, 10);
      }
    ));
  });
});
```

**Criterio de Completado:**
`cd frontend && npx vitest --run contrast.property.test` pasa con al menos 100 runs por propiedad.

**Dependencias:** Tarea 2.1

---

### Tarea 3.3: Verificar jerarquía de contraste entre tokens de texto

**Archivo:** `frontend/src/__tests__/contrast-utils.test.ts`
**Acción:** Añadir un bloque de tests que verifique la Propiedad 3 del diseño — que la jerarquía se mantiene en ambos modos:

```typescript
describe('Propiedad 3: jerarquía de contraste preservada', () => {
  const modes = [
    { name: 'claro', bg: '#f8fafc', primary: '#111827', secondary: '#374151', muted: '#6b7280' },
    { name: 'oscuro', bg: '#0f172a', primary: '#f1f5f9', secondary: '#d1d5db', muted: '#9ca3af' },
  ];

  modes.forEach(({ name, bg, primary, secondary, muted }) => {
    it(`modo ${name}: primary > secondary > muted`, () => {
      const rPrimary = contrastRatio(primary, bg);
      const rSecondary = contrastRatio(secondary, bg);
      const rMuted = contrastRatio(muted, bg);
      expect(rPrimary).toBeGreaterThan(rSecondary);
      expect(rSecondary).toBeGreaterThan(rMuted);
    });
  });
});
```

**Criterio de Completado:**
Tests de jerarquía pasan. Si fallan, ajustar los valores de tokens en Fase 1 hasta que la jerarquía se respete.

**Dependencias:** Tarea 1.1, Tarea 1.2, Tarea 1.3, Tarea 3.1

---

## Fase 4: Migración de Componentes

### Tarea 4.1: Migrar colores hardcodeados en `LoginScreen`

**Archivo:** `frontend/src/components/LoginScreen.tsx` (o `.jsx`)
**Acción:** Buscar todos los valores de color hardcodeados (hexadecimales, `rgb()`, nombres CSS) y reemplazarlos con los tokens semánticos correspondientes:
- Fondos → `var(--bg-base)`, `var(--bg-surface)`, etc.
- Texto principal → `var(--text-primary)`
- Texto secundario → `var(--text-secondary)`
- Colores de marca → `var(--brand-primary)`

**Criterio de Completado:**
`grep -n '#[0-9a-fA-F]\{3,6\}\|rgb(' frontend/src/components/LoginScreen.tsx` no devuelve ningún resultado. El componente se ve correctamente en ambos modos.

**Dependencias:** Tarea 1.1, Tarea 1.2, Tarea 1.3

---

### Tarea 4.2: Migrar colores hardcodeados en `AdminConsole`

**Archivo:** `frontend/src/components/AdminConsole.tsx` (o `.jsx`)
**Acción:** Mismo proceso que Tarea 4.1 para el componente `AdminConsole`.

**Criterio de Completado:**
`grep -n '#[0-9a-fA-F]\{3,6\}\|rgb(' frontend/src/components/AdminConsole.tsx` no devuelve ningún resultado. El componente se ve correctamente en ambos modos.

**Dependencias:** Tarea 1.1, Tarea 1.2, Tarea 1.3

---

### Tarea 4.3: Smoke test visual en ambos modos

**Archivo:** N/A (verificación manual / end-to-end)
**Acción:** Navegar por los flujos principales de la aplicación en modo claro y oscuro:
1. Pantalla de login — verificar que texto, labels, botones y campos son legibles
2. Panel de administración — verificar tablas, headers y texto secundario
3. Toggle de modo oscuro — verificar que la transición es instantánea y no deja colores residuales

**Criterio de Completado:**
Ningún elemento tiene texto invisible, bordes ilegibles, o contraste visiblemente insuficiente. El toggle funciona en cualquier página.

**Dependencias:** Tarea 4.1, Tarea 4.2
```

---

## Bugfix Task Sequence

For bugfix specs, always follow this order:

```markdown
## Fase 1: Reproducción

### Tarea 1.1: Escribir test que falla (reproduce el bug)

**Archivo:** `path/to/__tests__/bug-name.test.ts` (crear)
**Acción:** Escribir un test que reproduzca exactamente el comportamiento defectuoso. 
El test DEBE fallar antes del fix.

**Criterio de Completado:**
`npx vitest --run bug-name.test` falla con el error esperado.

**Dependencias:** Ninguna

---

## Fase 2: Fix

### Tarea 2.1: Implementar el fix

**Archivo:** `path/to/broken-file.ts`
**Acción:** [descripción exacta del cambio]

**Criterio de Completado:**
`npx vitest --run bug-name.test` pasa.

**Dependencias:** Tarea 1.1

---

## Fase 3: Regresiones

### Tarea 3.1: Tests de regresión para [Comportamiento Sin Cambios 1]

**Archivo:** `path/to/__tests__/regression.test.ts`
**Acción:** Para cada item del `## Comportamiento Sin Cambios` del bugfix.md, añadir un test.

**Criterio de Completado:**
Todos los tests de regresión pasan.

**Dependencias:** Tarea 2.1
```

---

## Quality Checklist

Before confirming tasks.md is complete:

- [ ] Every task names a specific file path
- [ ] Every "Acción" can be executed without reading other documents
- [ ] Every "Criterio de Completado" is observable (a command to run, a UI state to see)
- [ ] Every correctness property from `design.md` has a corresponding test task
- [ ] For bugfix specs: failing test is written before the fix
- [ ] Dependencies are explicitly stated for every task that has them
- [ ] The phase summary table matches the actual task count
