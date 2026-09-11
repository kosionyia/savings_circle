# Ajo — The Savings Circle

> A weekly savings circle (Ajo/Esusu): members pay a fixed amount each week, one member collects the pot by turn, and a bank robot confirms transfers that have actually cleared.

FastAPI backend built with **SQLModel + SQLite**, JWT authentication, and a bank-webhook ledger. Each circle has a turn order that determines the payout recipient for the current week.

---

## SYSTEM ARCHITECTURE

![ARCHITECTURAL DESIGN](https://lucid.app/lucidchart/00b8cebe-00e8-4656-b770-ea246dacb7f9/edit?viewport_loc=-331%2C-2464%2C3515%2C1714%2C0_0&invitationId=inv_e8c7c66a-25e1-48f9-af07-a411da3973dd)


## Table of Contents

- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Getting Started](#getting-started)
- [Demo Users](#demo-users)
- [Authentication](#authentication)
- [API Reference](#api-reference)
- [Data Models](#data-models)
- [Database](#database)
- [Configuration](#configuration)
- [Development](#development)

---

## How It Works

1. **Admin creates a circle** — sets `name`, `weekly_amount`, and `member_limit`.
2. **Members join** — self-join or admin-admits. Each member gets a `turn_position`.
3. **Admin sets turn order** — defines the rotation for payouts (each member exactly once).
4. **Weekly contributions** — each member posts a contribution of exactly `weekly_amount` for `current_week`. One contribution per member per week.
5. **Payout** — admin declares the payout to the member whose turn it is (`next_recipient`). The pot (sum of this week's contributions) is paid out and `current_week` increments.
6. **Bank confirmation** — a trusted bank robot confirms contributions via `X-API-Key` after money has cleared. Confirmation is idempotent and writes an audit `LedgerEntry` via background task.
7. **Health check** — view who has paid vs. who is behind for the current week.

Turn recipient is calculated as `((current_week - 1) % member_count) + 1` mapped to `turn_position`.

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| Framework | FastAPI `>=0.141.1` (with `[standard]` extras) |
| ORM / Validation | SQLModel + Pydantic v2 |
| Database | SQLite (`ajo.db` via `sqlite:///ajo.db`) |
| Auth | JWT (`HS256`, `PyJWT`), `bcrypt` password hashing |
| Server | Uvicorn (via `fastapi[standard]`) |
| Package Manager | `uv` (`pyproject.toml` + `uv.lock`) |
| Python | `>=3.14` |

---

## Project Structure

```
savings_circle/
├── app/
│   ├── main.py              # FastAPI app, lifespan, CORS, routers, timing middleware
│   ├── models/              # SQLModel tables
│   │   ├── user.py          # User, UserRole (admin/member)
│   │   ├── circles.py       # Circle
│   │   ├── membership.py    # Membership (unique: user+circle, circle+turn_position)
│   │   ├── contribution.py  # Contribution (unique: user+circle+week)
│   │   ├── payout.py        # Payout (unique: circle+week)
│   │   └── ledger.py        # LedgerEntry (audit trail for confirmed transfers)
│   ├── schemas/             # Pydantic request/response schemas
│   │   ├── auth.py
│   │   ├── circles.py
│   │   ├── contributions.py
│   │   ├── payouts.py
│   │   └── bank.py
│   ├── routes/              # API routers
│   │   ├── auth.py          # /auth
│   │   ├── circles.py       # /circles
│   │   ├── contributions.py # /circles/{id}/contributions
│   │   ├── payouts.py       # /circles/{id}/payouts
│   │   └── bank.py          # /bank
│   └── services/
│       ├── db.py            # engine, create_db_and_tables(), seed_demo_users()
│       ├── security.py      # hash/verify password, JWT create, constants
│       ├── dependency.py    # get_current_user, require_admin, require_bank_robot
│       ├── helpers.py       # circle/member helpers, next_recipient logic
│       └── ledger.py        # write_ledger_line (background task)
├── pyproject.toml
├── uv.lock
├── ajo.db                   # SQLite DB (created on first run, gitignored if configured)
└── README.md
```

---

## Requirements

- Python `>=3.14`
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`

---

## Getting Started

### 1. Clone and install

```bash
# with uv (recommended)
uv sync

# or with pip
pip install "fastapi[standard]>=0.141.1"
pip install sqlmodel bcrypt pyjwt python-multipart email-validator
```

### 2. Run the server

```bash
# with uv
uv run fastapi dev app/main.py
# or
uv run uvicorn app.main:app --reload

# with pip/venv
fastapi dev app/main.py
uvicorn app.main:app --reload
```

The server starts at `http://127.0.0.1:8000`.

- Interactive docs: `http://127.0.0.1:8000/docs` (Swagger UI)
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

On startup (`lifespan` in `app/main.py:36`) the app:
- Creates all tables (`SQLModel.metadata.create_all`)
- Seeds demo users if they do not exist

---

## Demo Users

Seeded by `app/services/db.py:23` on first run (password for all is `secret123`):

| Name | Email | Role | Purpose |
|------|-------|------|---------|
| Chairman Ade | `ade@ajo.com` | `admin` | Create circles, admit members, set turn order, declare payouts |
| Amaka | `amaka@ajo.com` | `member` | Regular member |
| Chinedu | `chinedu@ajo.com` | `member` | Regular member |

Create additional users via `POST /auth/register`.

---

## Authentication

### User JWT (Bearer)

- Login via `POST /auth/login` (OAuth2 password flow, `username` = email) to receive `access_token`.
- Send `Authorization: Bearer <token>` on all user-protected endpoints.
- Tokens are `HS256`, expire in 60 minutes (`app/services/security.py:8`), secret `ajo-dev-secret-not-for-production`.

Dependency: `app/services/dependency.py:14` (`get_current_user`), `require_admin` for admin-only routes.

### Bank Robot API Key

- Bank endpoints require `X-API-Key: argon-secret-ajo` (`app/services/security.py:9`).
- Dependency: `app/services/dependency.py:51` (`require_bank_robot`).

---

## API Reference

### Authentication — `app/routes/auth.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/register` | None | Register a new member (`UserRegister` → `UserResponse`). 409 if email exists. |
| `POST` | `/auth/login` | None | Login with `OAuth2PasswordRequestForm` (`username`/`password`). Returns `TokenResponse` (`access_token`, `token_type: bearer`). 401 on invalid credentials. |

### Circles — `app/routes/circles.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/circles` | Admin | Create a circle (`CircleCreate`: `name`, `weekly_amount`, `member_limit`). |
| `GET` | `/circles/{circle_id}` | Member or Admin | Get circle detail (`CircleOut` with `pot`, `turn_order`, `next_user_id/name`). |
| `POST` | `/circles/{circle_id}/join` | User | Current user joins the circle. 409 if already a member or circle is full. |
| `POST` | `/circles/{circle_id}/members` | Admin (circle admin) | Admit another user by `user_id` (`AdmitMember`). |
| `PUT` | `/circles/{circle_id}/turn-order` | Admin (circle admin) | Set rotation (`TurnOrderIn: user_ids`). Must include each member exactly once. |
| `GET` | `/circles/{circle_id}/health` | Member or Admin | Weekly health: `{ week, paid: MemberHealth[], behind: MemberHealth[] }`. |

`CircleOut` (`app/schemas/circles.py:57`) includes:
`id`, `name`, `weekly_amount`, `member_limit`, `current_week`, `admin_id`, `pot` (sum of current-week contributions), `member_count`, `turn_order[]`, `next_user_id`, `next_user_name`.

### Contributions — `app/routes/contributions.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/circles/{circle_id}/contributions` | Member | Record contribution for current week (`ContributeIn: amount`). Must equal `weekly_amount`. One per user per week (409 otherwise). Starts as `confirmed=false`. |
| `GET` | `/circles/{circle_id}/contributions/me` | Member | List current user's contributions in this circle ordered by week. |

### Payouts — `app/routes/payouts.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/circles/{circle_id}/payouts` | Admin (circle admin) | Declare payout for current week (`PayoutIn: user_id`). Must be the expected `next_recipient`; amount is the current pot. Increments `current_week`. 409 if already paid this week. |

### Bank — `app/routes/bank.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/bank/confirm` | `X-API-Key` | Confirm a transfer (`BankConfirmIn: contribution_id`). Sets `confirmed=true`, queues `write_ledger_line` as background task. 404 if not found, 409 if already confirmed. |
| `GET` | `/bank/ledger` | `X-API-Key` | List all `LedgerEntry` rows ordered by `id`. |

---

## Data Models

Defined in `app/models/`:

- **User** (`app/models/user.py:11`) — `id`, `name`, `email` (unique), `hashed_password`, `role` (`admin`|`member`)
- **Circle** (`app/models/circles.py:3`) — `id`, `name`, `weekly_amount`, `member_limit`, `current_week` (default 1), `admin_id`
- **Membership** (`app/models/membership.py:7`) — `id`, `user_id`, `circle_id`, `turn_position` — unique on `(user_id, circle_id)` and `(circle_id, turn_position)`
- **Contribution** (`app/models/contribution.py`) — `user_id`, `circle_id`, `amount`, `week`, `confirmed` — unique on `(user_id, circle_id, week)`
- **Payout** (`app/models/payout.py`) — `circle_id`, `user_id`, `amount`, `week` — unique on `(circle_id, week)`
- **LedgerEntry** (`app/models/ledger.py`) — audit row written by `app/services/ledger.py` after bank confirmation

Schemas (request/response) are in `app/schemas/` and map 1:1 to the routes above.

---

## Database

- **Engine**: `sqlite:///ajo.db` (`app/services/db.py:6`) with `check_same_thread=False`.
- **File**: `ajo.db` in the project root (created automatically; delete to reset).
- **Migrations**: none — tables are created via `SQLModel.metadata.create_all` on startup. For a fresh DB, stop the server, delete `ajo.db`, and restart.

---

## Configuration

Constants in `app/services/security.py:6`:

```python
SECRET_KEY = "ajo-dev-secret-not-for-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
BANK_API_KEY = "argon-secret-ajo"
```

> For production, move these to environment variables and use a strong, random `SECRET_KEY` and `BANK_API_KEY`.

Other app-level config:

- **CORS**: `allow_origins=["*"]` (`app/main.py:52`)
- **Timing middleware**: adds `X-Process-Time` header (`app/main.py:61`)

---

## Development

### Project conventions

- Routers use `APIRouter` with `prefix` and `tags` matching `openapi_tags` in `app/main.py:17`.
- Auth dependencies are in `app/services/dependency.py`; domain helpers in `app/services/helpers.py`.
- Turn-order updates use a two-phase commit (park at 1000+, then set real order) to avoid SQLite unique constraint collisions (`app/routes/circles.py:219`).

### Useful commands

```bash
# run with auto-reload
uv run fastapi dev app/main.py

# check lint/types (if configured)
uv run mypy app

# inspect DB directly
sqlite3 ajo.db "SELECT * FROM user;"
sqlite3 ajo.db "SELECT * FROM circle;"
```

### Example flow (via curl)

```bash
# 1. Login as admin
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=ade@ajo.com&password=secret123"
# -> { "access_token": "...", "token_type": "bearer" }

TOKEN=<access_token>

# 2. Create a circle
curl -X POST http://127.0.0.1:8000/circles \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Surulere Market Circle","weekly_amount":5000,"member_limit":5}'

# 3. Join as a member (login as amaka, then)
curl -X POST http://127.0.0.1:8000/circles/1/join \
  -H "Authorization: Bearer $MEMBER_TOKEN"

# 4. Contribute
curl -X POST http://127.0.0.1:8000/circles/1/contributions \
  -H "Authorization: Bearer $MEMBER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount":5000}'

# 5. Bank confirms the transfer
curl -X POST http://127.0.0.1:8000/bank/confirm \
  -H "X-API-Key: argon-secret-ajo" \
  -H "Content-Type: application/json" \
  -d '{"contribution_id":1}'

# 6. Declare payout (admin)
curl -X POST http://127.0.0.1:8000/circles/1/payouts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":2}'
```

---

## License

No license specified. Add one if you intend to distribute this project.
