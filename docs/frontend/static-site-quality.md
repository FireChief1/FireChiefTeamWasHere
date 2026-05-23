# Static Site Quality

## File Layout

Use safe relative file paths within the selected project folder. A simple
standalone site usually needs `index.html`; optional assets may live under
`assets/`, `css/`, or `js/`. Never write absolute paths or paths containing
`..`.

## Local Asset References

When HTML references local CSS, JavaScript, images, or other assets, the
referenced files should be produced in the same output set or already exist in
the selected project folder. External `https://` resources are allowed only
when the task benefits from them.

## Validation Expectations

Static web output is validated as web artifacts, not as Python. Checks should
confirm that at least one HTML file exists, HTML content is non-empty and
complete, local asset references are not broken, and task-specific visible
content is present.
