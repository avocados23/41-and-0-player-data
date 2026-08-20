# Git development and release workflow

This repository uses the same shared-branch workflow as the Fastify and
frontend repositories:

```text
feature/* or bugfix/* -> develop -> release/YYYY.M.DD -> production -> master
```

`develop` is the integration branch. A dated release branch is the exact
revision deployed to staging and production. `master` records the deployed
production state. Keep the branch roles synchronized across the repositories
when a release changes both data and the API.

## Branch rules

- Start feature and bugfix branches from the current `develop` branch.
- Include the issue number in every feature, bugfix, hotfix, and release branch
  name where applicable.
- Ordinary commits must use `#<issue-id> <issue title>`; merge commits are
  exempt. The local hook and CI enforce this format.
- Run applicable checks before merging.
- Merge locally with `git merge --no-ff`; do not squash or rebase shared-branch
  integrations.
- Delete completed topic, release, and hotfix branches after synchronization.

Examples:

```bash
git checkout develop
git pull origin develop
git checkout -b feature/123-update-pipeline-layout
# make changes and run checks
git add .
git commit -m "#123 Update pipeline layout"
git push --set-upstream origin feature/123-update-pipeline-layout
```

Merge a completed topic locally:

```bash
git checkout develop
git pull origin develop
git merge --no-ff feature/123-update-pipeline-layout
git push origin develop
git branch -d feature/123-update-pipeline-layout
```

## Release workflow

Create a dated release branch only from a green `develop`:

```bash
git checkout develop
git pull origin develop
git checkout -b release/2026.8.20
git push --set-upstream origin release/2026.8.20
```

Rehearse the data release and Fastify migration release together in staging.
Deploy the exact release branch revision. After production verification, merge
the release branch into both `master` and `develop` with `--no-ff`, push both,
and then delete the release branch.

```bash
git checkout master
git pull origin master
git merge --no-ff release/2026.8.20
git push origin master

git checkout develop
git pull origin develop
git merge --no-ff release/2026.8.20
git push origin develop
git branch -d release/2026.8.20
```

Hotfixes start from `master`, merge into `master` after validation, and then
merge into `develop` so the fix is not lost.

## Checks

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src scripts
```

Before a database release, also run the Fastify repository’s migration,
upgrade-from-V29, Prisma, entity-generation, and application checks. Never edit
an applied Flyway migration; use a new roll-forward migration in Fastify.

## One-time activation

After this workflow is merged on the current `master`, create `develop` from
that exact revision and publish it:

```bash
git checkout master
git pull origin master
git checkout -b develop
git push --set-upstream origin develop
```
