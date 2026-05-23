# Project Mode File Output Rules

## Target Folder

Project Mode works inside the selected project folder. Agents should produce
safe relative paths for files that belong in that folder. They must not assume
the current repository is the target unless the selected folder is this
repository.

## Safe Paths

Generated file paths must be relative, must not contain `..`, must not begin
with `/`, and must not target hidden or cache directories. Prefer concise names
such as `index.html`, `style.css`, `script.js`, `README.md`, or paths under
`assets/`, `css/`, `js/`, or `src/` when appropriate.

## Existing Projects

When the selected project folder already contains files, update the smallest
reasonable set of files. When it is empty and the user asks for a simple page
or artifact, create the minimal complete file set instead of modifying the
agent system's own application files.
