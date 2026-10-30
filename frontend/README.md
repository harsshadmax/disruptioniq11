# DisruptionIQ web app

Next.js 16 (App Router), React 19, TypeScript, Tailwind 4, shadcn/ui, TanStack Query. It displays what the API computes and sends the user's actions back; it makes no decisions of its own.

Setup is in the [root README](../README.md#run-it-locally). The API address is set with `NEXT_PUBLIC_API_URL` in `.env.local`.

## Layout

```
app/
├── (app)/      signed-in pages: dashboard, disruptions, approvals, simulate, audit, import, demo
└── login/      sign-in page
components/     dashboard panels, ripple map, plan controls, sidebar, shared UI
lib/            API client, generated OpenAPI types, query hooks
```

## Commands

```bash
npm run dev       # development server on http://localhost:3000
npm run lint
npm run build     # production build
npm run gen:api   # regenerate lib/api/schema.d.ts (the API must be running)
```
