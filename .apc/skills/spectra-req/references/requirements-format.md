# Requirements Document Format

## Document Structure

```
# [Title]

## Introducción
[Problem + context + central thesis + non-goals]

## Glosario
[Defined terms in Term_Underscore_Format]

## Requisitos
[Numbered requirements with User Stories + Acceptance Criteria]
```

---

## Section: Introducción

### What goes here

- **Problem statement** (2–3 paragraphs): What exists, what's broken, what's missing. Include why it matters.
- **Central thesis / "idea fuerza"** (1–2 sentences): The core insight that drives every decision in this spec.
- **Critical decisions**: What this IS (scope) and what it explicitly IS NOT (anti-scope). Both are equally important.
- **Narrative structure** (optional): If the feature has phases or a sequential flow, sketch it here.

### Example

```markdown
## Introducción

La aplicación NexoAI presenta problemas de contraste de color en los modos 
claro y oscuro. El texto desaparece contra los fondos, los botones son 
difíciles de ver y las etiquetas se confunden con las superficies. 
La aplicación ya utiliza CSS custom properties (design tokens) en 
`frontend/src/style/index.css`, pero los valores actuales no cumplen 
con la conformidad WCAG AA.

**Idea fuerza:** Un design system de tokens semánticos garantiza que 
cualquier combinación texto/fondo sea legible por diseño, no por accidente.

**Scope:** Este documento define los requisitos para establecer un sistema 
completo de tokens de color que garantice ratios de contraste adecuados 
en todos los componentes y modos de tema.

**No-scope:** No migrar la arquitectura de CSS variables a CSS-in-JS; 
no rediseñar la UI; no modificar la estructura de componentes.
```

---

## Section: Glosario

### Rules

- Define ONLY terms that appear in the requirements below — not general knowledge
- Each definition is **operational**: what it is, its purpose, how it behaves
- Format: `**Term_With_Underscores**: definition`
- Use the exact `Styled_Format` consistently throughout the document

### Example

```markdown
## Glosario

- **Sistema_de_Tokens**: El conjunto de CSS custom properties definidas en `:root` 
  y `[data-theme='dark']` dentro de `frontend/src/style/index.css` que controlan 
  todos los colores de la aplicación.

- **Ratio_WCAG_AA_Texto**: Ratio de contraste mínimo de 4.5:1 entre el color del 
  texto y su fondo, según WCAG 2.1 nivel AA para texto de tamaño normal.

- **Modo_Oscuro**: El tema visual aplicado cuando `data-theme='dark'` está activo.

- **Componente**: Cualquier componente React que renderiza elementos visuales 
  (LoginScreen, Header, AdminConsole, etc.).
```

---

## Section: Requisitos

### Numbering

- Flat: `1, 2, 3...`
- Hierarchical: `1, 1.1, 1.2, 2, 3, 3.1...`
- Use sub-requirements when a parent concept has distinct sub-behaviors that need separate criteria

### Each requirement

```markdown
### Requisito N[.M]: Descriptive Title

**Historia de Usuario:** Como [beneficiary], quiero [need], para que [value]

#### Criterios de Aceptación

1. [EARS criterion]
2. [EARS criterion]
3. [EARS criterion]

**Restricciones:** (optional — add when hard constraints exist)
- [constraint]
```

### Ordering requirements

Requirements should tell a story. A reader skimming the headers should understand the feature arc:

1. **Core concept** (what is this thing?)
2. **Primary behavior** (what does it do?)
3. **Component-specific behavior** (how does each part behave?)
4. **Edge cases and states** (errors, disabled, empty)
5. **Validation / testing** (how do we know it works?)
6. **Exclusions** (explicit scope limits)

---

## Worked Example (abbreviated)

```markdown
# Documento de Requisitos — Sistema de Contraste de Color

## Introducción

La aplicación NexoAI presenta problemas de contraste de color...

**Idea fuerza:** Contraste por diseño, no por accidente.

## Glosario

- **Sistema_de_Tokens**: CSS custom properties en `index.css`...
- **Ratio_WCAG_AA_Texto**: Ratio mínimo 4.5:1 según WCAG 2.1...

## Requisitos

### Requisito 1: Tokens semánticos con contraste WCAG AA

**Historia de Usuario:** Como usuario, quiero que todos los colores de texto 
sean legibles contra sus fondos, para poder usar la aplicación sin esfuerzo 
visual en cualquier modo de tema.

#### Criterios de Aceptación

1. THE Sistema_de_Tokens SHALL define tokens for: backgrounds (--bg-*), 
   text (--text-*), brand (--brand-*), accents (--accent-*), borders (--border-*), 
   and interactive states (--interactive-*).

2. WHEN Modo_Claro is active, THE Sistema_de_Tokens SHALL assign color values 
   where each text/background token combination meets Ratio_WCAG_AA_Texto of 4.5:1.

3. WHEN Modo_Oscuro is active, THE Sistema_de_Tokens SHALL assign color values 
   where each text/background token combination meets Ratio_WCAG_AA_Texto of 4.5:1.

4. THE Sistema_de_Tokens SHALL define both modes (`:root` for light, 
   `[data-theme='dark']` for dark) within `frontend/src/style/index.css`.

5. WHEN a new semantic token is added, THE Sistema_de_Tokens SHALL document 
   its purpose and valid background combinations in a CSS comment alongside 
   the definition.

### Requisito 2: Contraste de componentes UI

**Historia de Usuario:** Como usuario, quiero que los botones, bordes e iconos 
sean distinguibles de sus fondos, para identificar elementos interactivos sin 
dificultad.

#### Criterios de Aceptación

1. THE Sistema_de_Tokens SHALL define UI element tokens (buttons, borders, icons) 
   that meet Ratio_WCAG_AA_UI of 3:1 against adjacent surfaces in Modo_Claro.
   
[...]

### Requisito N: Exclusiones Explícitas

**Historia de Usuario:** Como desarrollador, quiero tener límites claros sobre 
lo que este spec NO modifica, para evitar scope creep y regresiones inesperadas.

#### Criterios de Aceptación

1. THE spec SHALL NOT migrate the CSS custom property architecture to CSS-in-JS.
2. THE spec SHALL NOT redesign the UI layout or component structure.
3. THE spec SHALL NOT modify TypeScript component logic unrelated to color tokens.
```

---

## Tips

- If you have more than 10 requirements, group them into sections with `##` headers
- An "Exclusiones Explícitas" requirement at the end is often the most valuable one — it prevents scope creep and misaligned expectations
- The Glossary is a contract: once defined, use terms exactly as written everywhere
