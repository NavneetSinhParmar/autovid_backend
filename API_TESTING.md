# Local API Testing

From the project directory, with local MongoDB running and Python dependencies installed:

```powershell
python test_company_api.py
```

The runner loads the Mongo URL from `.env.local`. It creates a randomly named
`autovid_api_test_<uuid>` database, generates temporary administrator credentials,
starts its own Uvicorn server on an available loopback port, and makes real HTTP
requests. You do not need to supply an administrator password or start a second
server manually. Existing `autovid_db` records and media are not used or deleted.
The runner stops its own server and drops only its generated database afterward.
If forcibly terminated, a test database with that prefix may remain.

Required packages are in `requirements.txt`; `Pillow` is required for logo tests.
The Mongo account needs permission to create/drop the temporary database.
Use local MongoDB or a dedicated test instance, not production credentials.

## Coverage

- Company create, read, update and delete.
- Login, wrong password, profile without a logo, and logout revocation.
- Password hashing, self-service password changes and administrator reset.
- Old password rejection after change; rejection of resetting another company's password.
- Weak password rejection and invalid user/company IDs.
- Company A/B isolation, anonymous rejection and privileged action checks.
- Pagination, search, sorting, visibility filtering and maximum page size.
- Valid logo upload/download and cross-company logo access rejection.
- Invalid logo rejected before a user is created.
- Company deletion removes the linked login account.
- Company-scoped customer/category/template/media/campaign/job list smoke tests.
- API health and OpenAPI availability.

Each test prints `ok`, `FAIL` or `ERROR`. The command returns exit code 0 only if
all tests pass; any failed test returns a nonzero exit code. Tests do not print
passwords or bearer tokens. Authentication tests run against a single API worker.

Run the separate unit/regression suite too:

```powershell
python -m unittest discover -s tests -v
```

## Scope

This is the company/auth integration suite, not a guarantee that every backend
workflow works. It does not exercise full customer CRUD/import, category/template
CRUD, campaign expansion, FFmpeg rendering, Redis/Celery delivery, Kokoro speech,
worker recovery, multi-worker logout revocation or load capacity. Resource-list
smoke tests only verify those listing contracts. Render and bulk integration
tests require Redis, workers and representative media fixtures separately.

The runner intentionally uses an unavailable loopback Redis port to isolate the
process-local rate limiter from your normal Redis data. It does not certify Redis
health. Production index checks stay strict in the temporary database.
