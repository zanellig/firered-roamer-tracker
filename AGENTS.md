Read [the contribution guide](CONTRIBUTING.md) before making changes.

## Publishing a release

1. Move the completed entries from `Unreleased` into a dated version section in
   `CHANGELOG.md`.
2. Update the project version in `pyproject.toml` and refresh `uv.lock`.
3. Commit and push the release changes.
4. Create and push the matching `vX.Y.Z` tag.
5. Confirm the `Release native applications` workflow publishes all three
   archives and `SHA256SUMS.txt`.

Use [.github/RELEASE_TEMPLATE.md](.github/RELEASE_TEMPLATE.md) when drafting
release notes manually. GitHub's generated-note categories are configured in
`.github/release.yml`.
