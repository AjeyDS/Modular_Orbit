# Modular Orbit Frontend

This folder currently contains a dependency-free static shell for the modular app. It is temporary scaffolding, not the target product UI.

The next frontend implementation should be a React/Vite app that reuses the strongest legacy Orbit UI patterns from `../../frontend` while speaking the modular backend contract in `../backend`.

Initial frontend goals:

- render enabled Module Instances in the sidebar
- show module dashboard blocks
- expose Item Chat as a side panel
- show non-complete lifecycle status clearly
- keep dashboard layout simple until the module spine works

For React development, run the backend and frontend separately:

```bash
cd ../backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd ../frontend
npm install
npm run dev
```

Then open:

```text
http://localhost:5173
```

For a FastAPI-served production build:

```bash
npm run build
cd ../backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/static/
```

## React Port Direction

The static shell should be replaced once the React Modular Frontend reaches parity for the first useful slices.

Recommended order:

1. Scaffold React/Vite in this folder.
2. Add a typed modular API client.
3. Build shell/sidebar/dashboard from `/shell/*`.
4. Port Logs.
5. Port Tasks.
6. Add Item Chat side panel.
7. Port Plans, Documents, Chat, and Settings one at a time.

Do not point the old React app directly at the modular backend without rewriting its API layer. The old app assumes endpoints like `/tasks`, `/log`, and `/kb`; the modular backend uses module-scoped endpoints such as `/modules/tasks`, `/modules/logs`, and `/modules/documents`.
