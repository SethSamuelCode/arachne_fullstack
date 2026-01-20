# Frontend Architecture

Next.js 15 application with TypeScript, Zustand state management, and Tailwind CSS.

## Directory Structure (`frontend/src/`)

| Directory | Purpose |
|-----------|---------|
| `app/` | Next.js App Router pages and layouts |
| `components/` | React components (see below) |
| `hooks/` | Custom React hooks |
| `stores/` | Zustand state stores |
| `lib/` | Utilities, API client, constants |
| `types/` | TypeScript type definitions |
| `i18n/` | Internationalization config |
| `middleware.ts` | Next.js middleware (auth, i18n) |

## Components (`components/`)

| Directory | Purpose |
|-----------|---------|
| `auth/` | Authentication components (login, register) |
| `chat/` | Chat interface components |
| `files/` | File upload/management components |
| `layout/` | Layout components (header, sidebar) |
| `ui/` | Reusable UI primitives (shadcn/ui) |
| `theme/` | Theme toggle, providers |
| `icons/` | Icon components |

## Hooks (`hooks/`)

| Hook | Purpose |
|------|---------|
| `use-auth.ts` | Authentication state and actions |
| `use-chat.ts` | Chat messaging with streaming |
| `use-conversations.ts` | Conversation CRUD operations |
| `use-websocket.ts` | WebSocket connection management |
| `use-local-chat.ts` | Local-only chat (no persistence) |

## State Management (`stores/`)

Uses Zustand for client-side state:

| Store | Purpose |
|-------|---------|
| `auth-store.ts` | User authentication state |
| `chat-store.ts` | Active chat messages |
| `conversation-store.ts` | Conversation list |
| `files-store.ts` | File upload state |
| `sidebar-store.ts` | Sidebar visibility |
| `theme-store.ts` | Dark/light mode |

## Utilities (`lib/`)

| File | Purpose |
|------|---------|
| `api-client.ts` | HTTP client for backend API |
| `server-api.ts` | Server-side API calls |
| `sse.ts` | Server-Sent Events handling |
| `jwt.ts` | JWT token utilities |
| `utils.ts` | General utilities |
| `constants.ts` | App constants |

## Commands

```bash
# Development
bun dev               # Start dev server
bun build             # Production build
bun test              # Run unit tests (Vitest)
bun test:e2e          # Run E2E tests (Playwright)

# Via Docker (for LLMs)
docker compose exec frontend bun dev
docker compose exec frontend bun test
```

## Key Patterns

### Authentication (HTTP-only cookies)

```typescript
import { useAuth } from '@/hooks/use-auth';

function Component() {
    const { user, isAuthenticated, login, logout } = useAuth();
}
```

### State Management (Zustand)

```typescript
import { useAuthStore } from '@/stores/auth-store';

// In component
const { user, setUser, logout } = useAuthStore();
```

### API Calls

```typescript
import { apiClient } from '@/lib/api-client';

// Client-side
const response = await apiClient.get('/api/v1/users/me');

// Server-side (in Server Components)
import { serverApi } from '@/lib/server-api';
const data = await serverApi.get('/api/v1/items');
```

### Internationalization (next-intl)

```typescript
import { useTranslations } from 'next-intl';

function Component() {
    const t = useTranslations('common');
    return <h1>{t('title')}</h1>;
}
```

Messages are in `messages/en.json` and `messages/pl.json`.

## Testing

- **Unit tests:** Vitest + React Testing Library
- **E2E tests:** Playwright
- Config files: `vitest.config.ts`, `playwright.config.ts`

```bash
# Run specific test file
bun test src/stores/auth-store.test.ts

# E2E in headed mode
bun test:e2e --headed
```
