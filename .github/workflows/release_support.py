"""Local release checks and draft-only, no-clobber publication for Actions.

This file never publishes unless invoked with the explicit ``publish`` command.
The workflow invokes it only for an explicitly approved publish=true request.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
COMMIT = re.compile(r"[0-9a-f]{40}")


def json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(arguments, *, binary=False):
    result = subprocess.run(arguments, capture_output=True, text=not binary, timeout=120)
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace") if binary else result.stderr
        raise RuntimeError(error.strip() or "Command failed: " + arguments[0])
    return result.stdout


def validate_inputs(tag, expected_commit, actual_commit, version, approval, publish):
    if not TAG.fullmatch(tag) or not COMMIT.fullmatch(expected_commit):
        raise ValueError("Use a vX.Y.Z tag and its full lowercase 40-character commit SHA")
    if actual_commit != expected_commit:
        raise ValueError("The checked-out tag does not resolve to the explicitly approved commit")
    if tag != "v" + version:
        raise ValueError("Tag, package version and expected commit must describe the same source")
    if publish and (approval.get("version") != version or approval.get("release_approved") is not True
                    or approval.get("decision") != "release_with_disclosed_known_limitation"):
        raise ValueError("Publication requires a committed, matching explicit release approval")


def validate_source(tag, expected_commit, publish):
    import ast
    import tomllib

    package = ast.parse(Path("neuron_flow/__init__.py").read_text(encoding="utf-8"))
    versions = [node.value.value for node in package.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if len(versions) != 1:
        raise ValueError("Package must declare one literal version")
    version = versions[0]
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    if project["project"]["version"] != version:
        raise ValueError("pyproject.toml and package versions differ")
    actual = command(["git", "rev-parse", "HEAD^{commit}"]).strip()
    tagged = command(["git", "rev-parse", tag + "^{commit}"]).strip()
    if tagged != actual:
        raise ValueError("The checked-out source differs from the requested tag")
    approval = json_file("RELEASE_APPROVAL.json")
    validate_inputs(tag, expected_commit, actual, version, approval, publish)
    return {"tag": tag, "version": version, "source_commit": actual,
            "publication_requested": publish, "release_approved": approval.get("release_approved") is True
            and approval.get("version") == version
            and approval.get("decision") == "release_with_disclosed_known_limitation",
            "approval_decision": approval.get("decision")}


def bundle(directory, facts):
    directory = Path(directory)
    version = facts["version"]
    names = [f"neuron_flow_v{version}.zip", f"neuron_flow_v{version}.zip.sha256",
             "SHA256SUMS.txt", "START_COLAB.ipynb", "delivery_checks.json"]
    for name in names:
        if not (directory / name).is_file() or (directory / name).is_symlink():
            raise ValueError("Missing release file: " + name)
    archive = directory / names[0]
    checksum = (directory / names[1]).read_text(encoding="utf-8").strip()
    if checksum != digest(archive) + "  " + archive.name:
        raise ValueError("Archive checksum file differs from the built ZIP")
    checks = json_file(directory / "delivery_checks.json")
    if (checks.get("version") != version or checks.get("sha256") != digest(archive)
            or checks.get("fresh_local_unpack_passed") is not True):
        raise ValueError("Fresh-unpack evidence does not match this exact ZIP")
    if facts["publication_requested"] and checks.get("release_approved") is not True:
        raise ValueError("Publication requires an approved build, not an unapproved candidate")
    with zipfile.ZipFile(archive) as zipped:
        if zipped.read("neuron_flow/SHA256SUMS.txt") != (directory / "SHA256SUMS.txt").read_bytes():
            raise ValueError("Published manifest differs from the manifest inside the ZIP")
        if zipped.read("neuron_flow/START_COLAB.ipynb") != (directory / "START_COLAB.ipynb").read_bytes():
            raise ValueError("Published notebook differs from the notebook inside the ZIP")
    files = [{"name": name, "bytes": (directory / name).stat().st_size,
              "sha256": digest(directory / name)} for name in names]
    attestation = {**facts, "actor": os.environ.get("GITHUB_ACTOR", "local-validation"),
                   "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
                   "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                   "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
                   "created_at_utc": datetime.now(timezone.utc).isoformat(),
                   "colab_acceptance_complete": checks.get("colab_acceptance_complete", False),
                   "artifacts": files}
    write_json(directory / "publication_attestation.json", attestation)
    files.append({"name": "publication_attestation.json",
                  "bytes": (directory / "publication_attestation.json").stat().st_size,
                  "sha256": digest(directory / "publication_attestation.json")})
    notes = Path("RELEASE_NOTES.md").read_text(encoding="utf-8")
    if facts["publication_requested"] and version not in notes.splitlines()[0]:
        raise ValueError("Release notes heading does not identify the approved version")
    (directory / "release-notes.md").write_text(notes, encoding="utf-8")
    manifest = {**facts, "files": files, "notes_sha256": digest(directory / "release-notes.md")}
    write_json(directory / "release-manifest.json", manifest)
    return manifest


def verify_bundle(directory, manifest, expected_commit):
    directory = Path(directory)
    validate_inputs(manifest["tag"], expected_commit, manifest["source_commit"], manifest["version"],
                    {"version": manifest["version"], "release_approved": manifest["release_approved"],
                     "decision": manifest["approval_decision"]}, True)
    if manifest.get("publication_requested") is not True:
        raise ValueError("This candidate was not built for a manual publication request")
    version = manifest["version"]
    required = {f"neuron_flow_v{version}.zip", f"neuron_flow_v{version}.zip.sha256",
                "SHA256SUMS.txt", "START_COLAB.ipynb", "delivery_checks.json", "publication_attestation.json"}
    files = manifest["files"]
    if {item["name"] for item in files} != required or len(files) != len(required):
        raise ValueError("Unexpected or duplicate release files")
    for item in files:
        path = directory / item["name"]
        if (path.name != item["name"] or path.is_symlink() or not path.is_file()
                or path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]):
            raise ValueError("Downloaded build artifact differs: " + item["name"])
    if digest(directory / "release-notes.md") != manifest["notes_sha256"]:
        raise ValueError("Release notes differ from the reviewed build artifact")
    attestation = json_file(directory / "publication_attestation.json")
    for field in ("tag", "version", "source_commit", "publication_requested", "release_approved", "approval_decision"):
        if attestation.get(field) != manifest[field]:
            raise ValueError("Publication attestation differs from the verified source")
    if attestation.get("artifacts") != [item for item in files if item["name"] != "publication_attestation.json"]:
        raise ValueError("Publication attestation does not identify these exact files")


class GitHub:
    def __init__(self, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository

    def api(self, endpoint):
        return json.loads(command(["gh", "api", "repos/" + self.repository + "/" + endpoint]))

    def tag_commit(self, tag):
        obj = self.api("git/ref/tags/" + tag)["object"]
        for _ in range(5):
            if obj["type"] == "commit":
                return obj["sha"]
            if obj["type"] != "tag":
                break
            obj = self.api("git/tags/" + obj["sha"])["object"]
        raise ValueError("Tag does not resolve to a commit")

    def find_release(self, tag):
        pages = json.loads(command(["gh", "api", "--paginate", "--slurp",
                                   "repos/" + self.repository + "/releases?per_page=100"]))
        matches = [release for page in pages for release in page if release["tag_name"] == tag]
        if len(matches) > 1:
            raise ValueError("Multiple releases use the requested tag")
        return matches[0] if matches else None

    def create_draft(self, tag, version, notes):
        command(["gh", "release", "create", tag, "--repo", self.repository, "--verify-tag", "--draft",
                 "--title", "Neuron Flow " + version, "--notes-file", str(notes)])
        release = self.find_release(tag)
        if release is None:
            raise RuntimeError("Created draft was not visible")
        return release

    def upload(self, tag, path):
        command(["gh", "release", "upload", tag, str(path), "--repo", self.repository])

    def refresh(self, release_id):
        return self.api("releases/" + str(release_id))

    def verify_asset(self, tag, asset, expected):
        if asset.get("state") != "uploaded" or asset["size"] != expected["bytes"]:
            raise ValueError("Remote asset is incomplete or differs: " + expected["name"])
        remote_digest = asset.get("digest")
        if remote_digest:
            if remote_digest != "sha256:" + expected["sha256"]:
                raise ValueError("Remote asset SHA-256 differs: " + expected["name"])
        else:
            with tempfile.TemporaryDirectory(prefix="neuron-release-download-") as temporary:
                command(["gh", "release", "download", tag, "--repo", self.repository,
                         "--pattern", expected["name"], "--dir", temporary])
                if digest(Path(temporary) / expected["name"]) != expected["sha256"]:
                    raise ValueError("Downloaded remote asset SHA-256 differs: " + expected["name"])

    def publish(self, tag):
        command(["gh", "release", "edit", tag, "--repo", self.repository, "--draft=false", "--latest"])
        release = self.find_release(tag)
        if release is None or release["draft"] is not False or release["prerelease"] is not False:
            raise RuntimeError("Publication was not confirmed by GitHub")
        return release


def publish_bundle(directory, manifest, expected_commit, github):
    verify_bundle(directory, manifest, expected_commit)
    if github.tag_commit(manifest["tag"]) != expected_commit:
        raise ValueError("Remote tag differs from the explicitly approved commit")
    release = github.find_release(manifest["tag"])
    if release is not None and release["draft"] is not True:
        raise ValueError("Release is already published; no files or metadata were changed")
    if release is not None and release.get("prerelease") is not False:
        raise ValueError("Existing draft has different release metadata; preserving it")
    expected = {item["name"]: item for item in manifest["files"]}
    if release is not None:
        assets = release["assets"]
        if len({item["name"] for item in assets}) != len(assets) or set(item["name"] for item in assets) - set(expected):
            raise ValueError("Draft contains unexpected or duplicate assets; preserving them")
        # Validate all existing files before uploading even the first missing one.
        for asset in assets:
            github.verify_asset(manifest["tag"], asset, expected[asset["name"]])
        if release.get("body", "").strip() != (Path(directory) / "release-notes.md").read_text(encoding="utf-8").strip():
            raise ValueError("Draft release notes differ; preserving existing metadata")
    else:
        release = github.create_draft(manifest["tag"], manifest["version"], Path(directory) / "release-notes.md")
    existing = {item["name"] for item in release["assets"]}
    for name, item in expected.items():
        if name not in existing:
            github.upload(manifest["tag"], Path(directory) / name)
    release = github.refresh(release["id"])
    if release["draft"] is not True or len(release["assets"]) != len(expected):
        raise ValueError("Draft changed during upload or file count differs")
    for asset in release["assets"]:
        github.verify_asset(manifest["tag"], asset, expected[asset["name"]])
    if github.tag_commit(manifest["tag"]) != expected_commit:
        raise ValueError("Remote tag changed during upload; the release remains a draft")
    return github.publish(manifest["tag"])


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "bundle"):
        sub = commands.add_parser(name)
        sub.add_argument("--tag", required=True)
        sub.add_argument("--expected-commit", required=True)
        sub.add_argument("--publish", action="store_true")
        if name == "bundle":
            sub.add_argument("--directory", required=True)
    sub = commands.add_parser("publish")
    sub.add_argument("--directory", required=True)
    sub.add_argument("--expected-commit", required=True)
    sub.add_argument("--repository", required=True)
    args = parser.parse_args()
    if args.command in {"validate", "bundle"}:
        facts = validate_source(args.tag, args.expected_commit, args.publish)
        if args.command == "bundle":
            bundle(args.directory, facts)
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
                output.write("version=" + facts["version"] + "\ncommit=" + facts["source_commit"] + "\n")
        print(json.dumps(facts, sort_keys=True))
    else:
        manifest = json_file(Path(args.directory) / "release-manifest.json")
        release = publish_bundle(args.directory, manifest, args.expected_commit, GitHub(args.repository))
        print(json.dumps({"url": release["html_url"], "tag": release["tag_name"], "draft": release["draft"]}))


if __name__ == "__main__":
    main()
