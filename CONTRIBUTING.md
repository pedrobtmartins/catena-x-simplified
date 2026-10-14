# Contributing

## Conventions

- **Language**: code, comments, commit messages and documentation are in English.
- **Scope**: the [Traceability KIT](https://github.com/eclipse-tractusx/eclipse-tractusx.github.io/tree/main/docs-kits/kits/traceability-kit)
  is the reference; [`docs/architecture.md`](docs/architecture.md) records the design and its
  decisions (ADRs). A change that alters a decision updates that document in the same pull request.
- **Dataspace access** goes through the `dataspace` module (Tractus-X SDK) behind its interfaces;
  domain code never calls the EDC or DTR directly and never names an aspect model URN outside
  `aspects/registry.py`.
- **Database changes** come with an Alembic migration (`backend/src/catenax_simplified/migrations`):
  change `storage/tables.py`, then
  `cd backend && CXS_DATABASE_URL=sqlite:///./scratch.db uv run alembic upgrade head && CXS_DATABASE_URL=sqlite:///./scratch.db uv run alembic revision --autogenerate -m "…"`,
  review the generated file and keep it in the same pull request. The app applies migrations at
  startup; `tests/test_migrations.py` fails when tables and migrations disagree.
- **Documentation** moves with the code: a new setting goes into `backend/.env.example` and the
  backend README, a new endpoint into the API table, a new screen into the web README.

## Setup

See the [quick start](README.md#quick-start). Python 3.12+ with [uv](https://docs.astral.sh/uv/),
Node.js 22.

## Before you push

The same checks CI runs ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest

cd ../web
npm ci
npm run build        # type-check and build

cd ..
docker build -t catenax-simplified .   # CI also builds the image and smoke-tests it
```

Changed a slide in `docs/pitch/slides/`? Rebuild the viewer: `python3 docs/pitch/build.py`.

## Tests

- Unit and API tests need no infrastructure: the DTR and submodel server are mocked at the HTTP
  level (`responses`) or through the fakes in `backend/tests/fakes.py`.
- **Supporting a new aspect model version**: add its official example payload from
  `sldt-semantic-models` to `backend/tests/fixtures/aspects/` (named `<namespace>-<version>.json`,
  unmodified), register the version in `aspects/registry.py` and, if its payload shape is new, add
  the mapping in `aspects/adapters.py`. The fixture test picks up every file in that folder.
- For a manual end-to-end check, run the app against `backend/devtools/mock_participant.py`.

## Branches and pull requests

- Work on a branch; open a pull request to `main`. CI (backend and web) must be green before
  merging.
- Commit messages follow a short conventional style: `feat(backend): …`, `feat(web): …`,
  `fix: …`, `docs: …`, with a body explaining what and why.
- Keep pull requests focused: one feature, fix or documentation topic each.

## License

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE). Third-party content needs a compatible license and an entry in
[`NOTICE.md`](NOTICE.md).
