# Orange ATS Recommendations (as of February 19, 2026)

## Timeline (Now to Next Wednesday)
- **Today (Feb 19, 2026):** Finalize UI frame, project structure, and MVP stack decisions.
- **Fri-Mon (Feb 20-23, 2026):** Implement auth, candidate module, and API contracts.
- **Tue (Feb 24, 2026):** Add reporting and caching, run load and query tests.
- **Wed (Feb 25, 2026):** Freeze architecture v1, review risks, and deployment readiness.

## 1) Application Architecture
### Option A: Modular Monolith (Recommended for Phase 1)
- One deployable backend with clear modules: Auth, Jobs, Candidates, Interviews, Reports, AI.
- Faster delivery and simpler operations while still supporting scale.
- Best fit for your current team size and current UI-first phase.

### Option B: Microservices (Later)
- Independent services per domain.
- Better isolated scaling but much higher complexity (DevOps, tracing, consistency, queues).

### Recommendation
- Start with **modular monolith + API-first design**.
- Enforce boundaries in code (`apps/` domains), keep async tasks via queue, extract services only when needed.

## 2) Technology Stack
### Frontend
- **HTML + CSS + JavaScript + Bootstrap 5** for fast UI delivery (your current plan).
- Keep reusable components using small JS modules and shared style tokens.
- Optional phase-2 upgrade: React/Vue only if interactivity becomes heavy.

### Backend
- **Python + Django + Django REST Framework**.
- Use REST endpoints and OpenAPI schema from day one.
- Background jobs: **Celery + Redis**.

### Database (200,000+ candidates)
- **PostgreSQL** (primary system of record).
- Use indexing and partitioning strategy where needed (for audit/event/time-heavy tables).
- Add **Redis** for cache/session/rate-limit support.

### Code Reusability Strategy
- Shared DTOs and validation contracts.
- Service layer per domain.
- Reusable query filters/pagination utilities.
- Central design tokens + shared table/form components on frontend.

## 3) Infrastructure
### API Structure
- Versioned REST API: `/api/v1/...`
- Domain grouped endpoints:
  - `/api/v1/auth/...`
  - `/api/v1/candidates/...`
  - `/api/v1/jobs/...`
  - `/api/v1/interviews/...`
  - `/api/v1/reports/...`

### Load Balancing
- **Nginx** in front of app instances (round-robin, least-conn as needed).
- Stateless app servers; sessions via secure cookies/Redis-backed session if needed.

### Cache Strategy
- Redis cache-aside for dashboard/report read paths.
- TTL-based eviction for derived data.
- Cache keys by tenant + endpoint + filter hash.

## 4) Code Commits (Local GitHub Account)
- Install Git locally, configure username/email.
- Create repo and branch strategy:
  - `main` (protected), `develop`, `feature/*`
- Commit convention:
  - `feat: add candidate list screen`
  - `fix: handle empty interview stage`
  - `chore: update docker compose`
- PR required before merging to `main`.

## 5) Plugins / Libraries
### Login / Authentication
- Start with Django auth + session/cookie flow.
- For social/SAML/OIDC expansion: **django-allauth** or **Auth0**.

### Reporting
- In-app charts: **Chart.js**.
- BI layer option: **Metabase** (embedded) if advanced analytics needed.

### AI Features
- CV parsing, ranking, semantic search:
  - embeddings + vector search using **PostgreSQL + pgvector**.
- Use async jobs for AI processing (Celery workers).

### Other Core Features
- Validation: DRF serializers
- Rate limiting: DRF throttling + Redis
- Audit logs: dedicated DB tables + retention policy

## 6) Deployment (Docker Recommendation)
### Recommended Baseline
- Docker Compose for local/dev/staging:
  - `web` (Django + Gunicorn)
  - `worker` (Celery)
  - `redis`
  - `postgres`
  - `nginx`
- Use Docker volumes for PostgreSQL persistent data.

### Production Path
- Short term: VM + Docker Compose + Nginx + backup/monitoring.
- Growth path: Kubernetes with HPA for autoscaling.

## Final Stack Recommendation (v1)
- **Frontend:** HTML, CSS, JS, Bootstrap 5
- **Backend:** Django + DRF
- **DB:** PostgreSQL
- **Cache/Queue:** Redis + Celery
- **Infra:** Nginx + Docker Compose (then Kubernetes when needed)
- **Reporting:** Chart.js (Metabase optional)
- **AI:** pgvector + embedding workflow
