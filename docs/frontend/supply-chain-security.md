# Frontend Supply Chain Security

## Keep the Dependency Surface Small

WHY: Frontend packages bring transitive dependencies and install-time behavior.
Supply-chain incidents can compromise packages that look unrelated to the UI
feature being built.

RULE: Add a frontend dependency only when the product need is clear and the
same behavior would be meaningfully worse to build locally. The initial React
UI allows only React, React DOM, TypeScript, Vite, the Vite React plugin, and
React type packages.

GOOD:
```json
"dependencies": {
  "react": "19.2.6",
  "react-dom": "19.2.6"
}
```

BAD:
```json
"dependencies": {
  "@some/ui-kit": "^1.0.0",
  "state-manager-of-the-week": "latest"
}
```

## Pin Exact Versions

WHY: Range specifiers can silently pull a newer package during install. That is
dangerous when the project is local-first and expected to be reproducible.

RULE: Use exact versions in `package.json`, commit `package-lock.json`, and use
`npm ci --ignore-scripts` for installs.

GOOD:
```json
"vite": "8.0.14"
```

BAD:
```json
"vite": "^8.0.0"
```

## Disable Install Scripts by Default

WHY: Lifecycle scripts are a common escalation point in npm incidents because
they execute during install before application code runs.

RULE: Keep `ignore-scripts=true` in `.npmrc`. If a package genuinely requires
install scripts, do not add it until the risk, maintainer history, and
alternative options are reviewed.

GOOD:
```ini
ignore-scripts=true
save-exact=true
audit=true
```

BAD:
```bash
npm install some-package
```

## Verify Before Merging

WHY: A minimal dependency set still needs continuous verification. Lockfiles
reduce drift, but they do not replace audit checks.

RULE: Run these checks for frontend changes:

```bash
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run audit
npm --prefix frontend run audit:signatures
npm --prefix frontend run build
```

If audit signatures fail because dependencies were not installed from a
supported registry, stop and inspect the lockfile and registry source before
shipping.

## Avoid Convenience Packages Early

WHY: UI kits, icon libraries, markdown renderers, syntax highlighters, routers,
and state libraries can be useful, but they also multiply the dependency graph.

RULE: The first React migration should build the project workspace with local
CSS and React state. Add libraries only after a concrete feature proves the
need.

GOOD:
```tsx
const [selectedProject, setSelectedProject] = useState<ProjectRecord | null>(null);
```

BAD:
```tsx
import { EverythingProvider } from "large-ui-platform";
```
