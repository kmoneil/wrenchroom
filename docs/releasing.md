# Releasing wrenchroom

A release is a version tag on `main`. Pushing it runs
[`release.yml`](../.github/workflows/release.yml), which builds the files, proves
them, waits for a maintainer to approve, publishes them to PyPI, and makes the
GitHub release.

PyPI trusts the workflow itself (Trusted Publishing): its publisher for `wrenchroom`
names this repository, the workflow file `release.yml` and the environment `pypi`.
No API token is stored anywhere. Renaming the file or the environment breaks
publishing until the publisher on PyPI is changed to match, which
`tests/test_release.py` guards.

## Before: a dry run

Actions, **release**, **Run workflow** on `main`. Only the build job runs: the sdist
and wheel are built and checked, and the wheel is installed in a clean environment and
run on the README's example. Locally, the same check is:

```console
$ uv run python scripts/lanes.py release-check
```

## The release

1. **Bump the version.** In a pull request, set `__version__` in
   `src/wrenchroom/__init__.py` to the release, `0.1.0` say: no `.dev`. Merge it once
   CI is green.
2. **Tag the merge commit, and push the tag.**

   ```console
   $ git switch main && git pull --rebase
   $ git tag -a v0.1.0 -m "wrenchroom 0.1.0"
   $ git push origin v0.1.0
   ```

3. **The build job runs.** It refuses a tag that doesn't name the package's version
   (`v` and all), or names a `.dev` or `+local` one, then builds and proves the files
   as the dry run does.
4. **Approve the deployment.** The publish job waits on the `pypi` environment:
   Actions, the run, **Review deployments**. Approving publishes. This is the step that
   can't be undone: PyPI never takes the same version twice.
5. **The GitHub release** is made for the tag, with the same files and notes from the
   pull requests merged since the last one.
6. **Open the next version.** In a pull request, set `__version__` to the next
   development version, `0.1.1.dev0` say.

## When a release is wrong

Don't delete it: a version, once on PyPI, can't be uploaded again. Yank it on PyPI
(the project's **Manage**, the release, **Options**, **Yank**), which keeps it out of
installs that don't name it exactly, and release a fixed version with the next number.

## What proves a release

`scripts/release.py`, which the build job runs:

- the tag names the version in `src/wrenchroom/__init__.py`, and the version is a
  release (PEP 440, no `.dev`, no `+local`);
- the sdist holds nothing private or generated: none of the gitignored working
  directories, no model file, nothing the examples write;
- the wheel holds its licences (Apache-2.0, and three.js's MIT) and the 3D view's
  bundle;
- the wheel, installed where the checkout can't be seen, says its version, checks the
  README's example bracket to the README's verdicts (exit 1, as a fastener fails),
  and writes its 3D view.
