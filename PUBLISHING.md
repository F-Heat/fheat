# Publishing `fheat` to PyPI

How to build and release `fheat` so users can `pip install fheat` / `uv add fheat`.

The distribution name is **`fheat`**; it ships three import packages
(`fheat_core`, `fheat_nrw`, `fheat_flex`) with optional extras
(`nrw`, `holidays`, `excel`, `full`, `dev`).

---

## One-time setup

1. Create accounts on **[TestPyPI](https://test.pypi.org)** and **[PyPI](https://pypi.org)**, and enable 2FA on both.
2. Create an **API token** on each (Account settings → *API tokens*). Start with an account-scoped token; after the first upload you can replace it with a project-scoped token for `fheat`.
3. Install the build tooling (already in the `dev` extra):

   ```bash
   pip install -e ".[dev]"      # brings in build + twine (and pytest)
   # or standalone:  pip install build twine
   ```

> The name `fheat` was free on PyPI at the time of writing — the first upload claims it.

---

## Release checklist

Run from the repository root, inside your virtual environment.

1. **Bump the version** in `pyproject.toml` (`version = "X.Y.Z"`).
   PyPI **rejects re-uploading an existing version**, so every upload needs a new number.
   `fheat_core.__version__` is read from the installed metadata, so there's only this one place to change.
2. **Run the tests** and confirm they pass:

   ```bash
   pytest -m "not network"
   ```
3. **Clean and build** fresh artifacts:

   ```bash
   rm -rf dist/
   python -m build           # -> dist/fheat-X.Y.Z-py3-none-any.whl + .tar.gz
   ```
4. **Validate** the artifacts:

   ```bash
   python -m twine check dist/*
   ```
5. **Upload to TestPyPI first** and smoke-test the install:

   ```bash
   python -m twine upload --repository testpypi dist/*
   #   username: __token__
   #   password: <your TestPyPI token>

   # Install from TestPyPI (dependencies still resolve from real PyPI):
   pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ "fheat[nrw]"
   python -c "import fheat_core; print(fheat_core.__version__)"
   ```
6. **Upload to PyPI:**

   ```bash
   python -m twine upload dist/*
   #   username: __token__
   #   password: <your PyPI token>
   ```
7. **Tag the release** in git:

   ```bash
   git tag -a vX.Y.Z -m "fheat X.Y.Z"
   git push origin vX.Y.Z
   ```

---

## Using `uv` instead

```bash
uv build                                   # -> dist/*.whl + *.tar.gz

# TestPyPI:
uv publish --publish-url https://test.pypi.org/legacy/ --token <TestPyPI token>

# PyPI:
uv publish --token <PyPI token>
```

---

## How users install after a release

```bash
pip install fheat            # core pipeline + flexible adapter
pip install "fheat[nrw]"     # + NRW auto-download adapter   (quote the brackets in zsh)
pip install "fheat[full]"    # everything

uv add fheat                 # in a uv-managed project
uv add "fheat[nrw]"
uv pip install fheat         # into a uv virtual environment
```

---

## Recommended: Trusted Publishing (no stored tokens)

The most secure setup is PyPI **Trusted Publishing** via GitHub Actions OIDC: you
register `fheat` as a trusted publisher on PyPI (project → *Publishing*), and a
tagged release triggers a workflow that builds and uploads with no API token stored
anywhere. Once a GitHub repository exists, this replaces steps 5–6 above with a
`git push` of the tag. (Ask and this can be scaffolded.)

---

## Notes

- `dist/`, `build/`, and `*.egg-info/` are git-ignored — never commit build artifacts.
- A version can be uploaded to PyPI **once**; to fix a bad release, bump the version and re-upload.
- Keep `TestPyPI` uploads for rehearsal; they don't affect the real index.
