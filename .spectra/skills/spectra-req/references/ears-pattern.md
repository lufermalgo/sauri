# EARS Notation Reference

EARS (Easy Approach to Requirements Syntax) is a structured pattern for writing requirements that are unambiguous, testable, and traceable.

## Core Patterns

### Ubiquitous (always true)
```
THE [system/component] SHALL [behavior]
```
Use for behaviors that must always hold, regardless of condition.

**Example:**
```
THE Sistema_de_Tokens SHALL define semantic tokens for backgrounds (--bg-*), 
text (--text-*), brand (--brand-*), and interactive states (--interactive-*).
```

---

### Event-driven (triggered by condition or event)
```
WHEN [condition or event], THE [system/component] SHALL [behavior]
```
Use when a behavior is triggered by something happening.

**Example:**
```
WHEN the user submits a form with invalid data, THE SYSTEM SHALL display 
validation errors adjacent to the affected fields.

WHEN Modo_Oscuro is active, THE Sistema_de_Tokens SHALL assign color values 
where each text/background combination meets Ratio_WCAG_AA_Texto of 4.5:1.
```

---

### Conditional (optional feature or state)
```
WHERE [feature or condition is true], THE [system/component] SHALL [behavior]
```
Use for behaviors that only apply in certain configurations or contexts.

**Example:**
```
WHERE a user has administrator role, THE Sistema SHALL display the admin console 
link in the navigation menu.
```

---

### Exception (error handling, alternative paths)
```
IF [exception condition], THEN THE [system/component] SHALL [alternative behavior]
```
Use for error states, fallbacks, and edge cases.

**Example:**
```
IF the database connection fails during login, THEN THE SYSTEM SHALL display 
an error message and log the failure — without exposing internal details to the user.

IF un Participante no entiende la diferencia entre prompt y skill, THEN THE 
mentor SHALL intervene to clarify before advancing to Phase 2.
```

---

### Universal (for all instances in a set)
```
FOR ALL [set of things], [action or condition] SHALL [result]
```
Use when a behavior must hold across every member of a defined set.

**Example:**
```
FOR ALL valid (foreground, background) token pairs defined in the 
Sistema_de_Tokens, the calculated contrast ratio SHALL meet the 
corresponding WCAG AA threshold.
```

---

## Combining Patterns

You can combine patterns to express complex conditions:

```
WHEN [event], IF [exception], THEN THE [component] SHALL [behavior]

WHEN a user attempts login, IF their account is locked, THEN THE SYSTEM 
SHALL display a "account locked" message and redirect to the support page.
```

---

## Quality Checklist

Before writing a criterion, ask:

1. **Observable?** Can someone verify this without interpreting it? "Loads fast" fails. "Responds in under 200ms" passes.
2. **Single behavior?** Each criterion expresses one thing. If you use "and", consider splitting.
3. **Traceable?** Can this become a test case? If the answer is "maybe", rewrite it.
4. **Stakeholder clear?** Is it obvious who benefits and from what?

---

## What EARS is NOT

- Not pseudo-code — don't describe implementation
- Not UI specifications — describe behavior, not layout
- Not assumptions — if it could be wrong, make it explicit or ask

---

## Glossary Term Convention

Terms defined in the Glossary appear in `Term_With_Underscores` format throughout requirements.

```
THE Componente LoginScreen SHALL use exclusively tokens from the 
Sistema_de_Tokens — no hardcoded color values.
```

This creates a "shared language" — any reader knows exactly what LoginScreen and Sistema_de_Tokens mean because they're defined once in the Glossary.
