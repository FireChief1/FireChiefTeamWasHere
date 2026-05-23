# Static UI Quality

Static HTML/CSS output should be usable, inspectable, and easy to preview. It
does not need a frontend framework unless the user asks for one or the project
already uses one.

## Baseline Requirements

Every static page should include:

- `<!doctype html>`
- `<html lang="...">`
- `<meta charset="UTF-8">`
- Responsive viewport meta tag.
- A meaningful `<title>`.
- Semantic landmarks when useful: `header`, `main`, `section`, `footer`.
- Content that matches the user's requested topic and existing project intent.

## Visual Quality

Use restrained CSS that supports readability:

- Clear type scale.
- Adequate contrast.
- Responsive layout with sane max widths.
- Spacing that works on mobile and desktop.
- No text overlap or clipped buttons.

Avoid generic sample pages when the selected project already has a topic. If
the current page is about space, a safe improvement should preserve that topic
unless the user asks to replace it.

## Asset Safety

For local static output:

- Do not reference missing CSS, JS, image, or font files.
- Prefer inline CSS for very small single-file tasks.
- If creating assets, include them in the output set and use safe relative
  paths.
- Never use `../` paths or hidden/cache folders.

## Review Checklist

Check:

- HTML has a title and at least one meaningful heading.
- CSS selectors match actual elements/classes.
- Local asset references exist.
- The page works without a build step unless a build step is part of the
  project.
- Generated text is not placeholder filler.

## Good Output

A single `index.html` with semantic structure and scoped inline CSS for a
small page request.

## Bad Output

A Python module that writes an HTML file when the user asked for a simple
static page.
