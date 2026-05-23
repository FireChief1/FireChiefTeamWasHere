# HTML and CSS Standards

## Static HTML Output

For a simple static page request, generate a directly usable `index.html`.
Use a complete HTML document with `<!doctype html>`, `<html lang="...">`,
`<head>`, `<meta charset="utf-8">`, a responsive viewport meta tag, a
meaningful `<title>`, and a visible `<body>` with a clear primary heading.

Prefer semantic HTML elements such as `header`, `main`, `section`, `article`,
`nav`, and `footer` when they fit the content. Do not generate Python,
Streamlit, or pytest files for a plain HTML task.

## Styling

Use restrained, readable CSS that supports desktop and mobile widths. For a
single small page, inline CSS inside `index.html` is acceptable. For larger
pages or repeated styling, use `style.css` and reference it with a safe
relative path.

Avoid decorative complexity that makes the page hard to inspect. Text must be
legible, spacing must be consistent, and interactive-looking elements should
have a clear purpose.

## Accessibility

Every page should have a meaningful title, one clear `h1`, readable contrast,
and descriptive link/button text. Images must have `alt` text unless they are
pure decoration. Do not rely on color alone to communicate meaning.
