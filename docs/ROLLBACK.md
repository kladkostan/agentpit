# Rolling back the WorkOS AuthKit cutover

Read this before reverting. There is exactly one conflict and it is in a test
file, so the temptation under pressure is to fight it — don't. Take the
pre-cutover file wholesale, as below.

## What to revert

```
git revert 3f707d0     # feat(auth): AuthKit is the only way in
```

That single commit is the whole cutover: it closed `/register`, `/login` and
`/auth/google`, removed the legacy bearer path from `current_user`, and took
the password form out of the sign-in dialog. It touches both `agentpit/` and
`ui/src/`.

## The one expected conflict

`git revert` stops in `tests/api/test_auth.py` with two conflicted hunks — the
import block, and the `/me/password` section. Nothing else conflicts:
`git merge-tree 3f707d0 HEAD 3f707d0^` reports every file under `agentpit/`
and `ui/src/` merging clean, and `tests/api/conftest.py` deleting clean.

The cause is `70b48ca` (`test(auth): cover the two live paths the cutover left
untested`), which landed after the cutover and edited the same file.

**Resolution — take the pre-cutover file, do not hand-merge:**

```
git checkout 3f707d0^ -- tests/api/test_auth.py
git revert --continue
```

The post-cutover tests in that file cannot survive the revert anyway: they
drive sign-in through the `sign_in` fixture in `tests/api/conftest.py`, and the
revert deletes that file.

`tests/services/test_auth_service.py` also gained tests in `70b48ca` and does
**not** conflict. Those keep passing after the revert — they exercise
`AuthService.login`, `JwtCoder` and `hash_password`, all of which the revert
restores rather than removes.

## Rebuild the caddy image

The UI half of the cutover is in the same commit, and the UI reads its WorkOS
configuration at **build** time — `deploy/Dockerfile.ui` bakes
`VITE_WORKOS_CLIENT_ID` / `VITE_WORKOS_REDIRECT_URI` in as `ARG`/`ENV`. A
reverted `agentpit/` with a stale bundle is the worst of both: the backend
accepts passwords again while the shipped dialog still has no password field.

```
docker compose -f deploy/docker-compose.prod.yml build caddy
docker compose -f deploy/docker-compose.prod.yml up -d caddy api
```

## Why reverting is safe

- **The passwords are still there.** `TableWrite.link_workos_identity`
  preserves `PASSWORD_HASH` when it stamps `WORKOS_USER_ID` — deliberately,
  for exactly this. The legacy accounts can log in with their old passwords
  the moment `/login` answers again, and `AuthService.login` and
  `change_password` were never deleted.
- **Sessions minted after the deploy keep working — if you leave the WorkOS
  variables in place.** The reverted `make_current_user_dep` takes a
  `JwtCoder` *and* an optional `AuthKitVerifier`, so it honours a legacy
  bearer token, an AuthKit access token, and every `X-API-Key`. But the
  verifier is built only when `WORKOS_CLIENT_ID` is set (the issuer and JWKS
  URL both derive from it). **Do not strip the WorkOS environment variables as
  part of the rollback** — that turns a safe revert into an instant sign-out
  for everyone who signed in while the cutover was live.
- **No schema change to undo.** `WORKOS_USER_ID` is an added, nullable column.
  Rows stamped with it are simply carrying a value nothing reads after the
  revert.
- **Nothing was deleted.** `JwtCoder`, `agentpit/auth/passwords.py`, the Google
  verifier, `GoogleSignInButton.tsx` and `googleAuth.ts` all still exist —
  removing them is plan 4's job, and doing it is what makes this revert stop
  being cheap.

## Do not run the user migration on the way back

`scripts/migrate_users_to_workos.py` is forward-only and is not a prerequisite
in either direction. It also cannot run against a reverted image: it selects
`WORKOS_USER_ID` with `create_tables=False`, so it depends on a container that
has already added the column.
