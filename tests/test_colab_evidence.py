"""Synthetic local assertions only: these tests are not actual Colab acceptance."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.colab_evidence import CHECKS, validate_colab_evidence


PACKAGE = "1" * 64
FIXTURE = "2" * 64
PROJECT = Path(__file__).resolve().parents[1]


def synthetic_assertion():
    snapshot = {
        "artifact_hashes": {"summary.csv": "3" * 64, "details.json": "4" * 64, "source.csv": FIXTURE},
        "step_attempts": {f"SYNTHETIC-TEST-JOB-{index:03d}": {"validate": 1, "calculate": 1, "verify": 1}
                          for index in range(100)},
    }
    return {
        "schema_version": 1, "status": "completed", "version": "0.2.1",
        "package_manifest_sha256": PACKAGE, "fixture_sha256": FIXTURE, "source_sha256": FIXTURE,
        "recorded_at_utc": "2026-01-01T00:05:00Z",
        "actual_runtime": {"google_colab_importable": True,
                           "runtime_marker_names": ["SYNTHETIC_UNIT_TEST_MARKER"],
                           "python_version": "3.12.0", "runtime_version": "SYNTHETIC-NOT-COLAB",
                           "started_at_utc": "2026-01-01T00:00:00+00:00"},
        "checks": {check: True for check in CHECKS},
        "before": snapshot, "after": copy.deepcopy(snapshot),
        "manual_download_confirmation": {"actor": "SYNTHETIC TEST, NOT A REAL DOWNLOAD",
                                         "confirmed_at_utc": "2026-01-01T00:02:00Z", "received": True},
    }


class ColabEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-colab-evidence-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic.json"

    def validate(self, evidence=None):
        if evidence is not None:
            self.path.write_text(json.dumps(evidence), encoding="utf-8")
        return validate_colab_evidence(self.path, version="0.2.1",
                                       package_manifest_sha256=PACKAGE, fixture_sha256=FIXTURE)

    def test_omitted_evidence_is_not_run_and_does_not_write(self):
        before = list(Path(self.temporary.name).iterdir())
        result = validate_colab_evidence(None, version="0.2.1",
                                         package_manifest_sha256=PACKAGE, fixture_sha256=FIXTURE)
        self.assertEqual(result["status"], "not_run")
        self.assertIs(result["complete"], False)
        self.assertIsNone(result["evidence_path"])
        self.assertEqual(list(Path(self.temporary.name).iterdir()), before)

    def test_synthetic_consistent_assertion_is_accepted_without_changing_input(self):
        self.path.write_text(json.dumps(synthetic_assertion()), encoding="utf-8")
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        result = self.validate()
        self.assertEqual(result["status"], "accepted")
        self.assertIs(result["complete"], True)
        self.assertIn("not remote attestation", result["reason"])
        self.assertEqual(result["evidence_path"], str(self.path.resolve()))
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before)

    def test_default_template_does_not_claim_acceptance(self):
        template = json.loads((PROJECT / "docs/colab_acceptance_TEMPLATE.json").read_text())
        self.assertEqual(template["status"], "not_run")
        self.assertTrue(all(value is False for value in template["checks"].values()))
        self.assertIs(template["manual_download_confirmation"]["received"], False)
        self.assertEqual(self.validate(template)["status"], "invalid")

    def test_missing_unreadable_or_malformed_evidence_returns_invalid_reason(self):
        self.assertEqual(self.validate()["status"], "invalid")
        for data in ("{bad json", "[]", '{"x":NaN}', '{"schema_version":1,"schema_version":1}'):
            with self.subTest(data=data):
                self.path.write_text(data, encoding="utf-8")
                result = self.validate()
                self.assertEqual(result["status"], "invalid")
                self.assertIs(result["complete"], False)
                self.assertTrue(result["reason"])

    def test_package_fixture_source_version_and_schema_identity_must_match(self):
        cases = [("schema_version", True), ("schema_version", 1.0), ("schema_version", 2),
                 ("version", "0.2.0"), ("package_manifest_sha256", "a" * 64),
                 ("fixture_sha256", "b" * 64), ("source_sha256", "c" * 64),
                 ("package_manifest_sha256", "not-a-hash"), ("status", "not_run")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                evidence = synthetic_assertion()
                evidence[key] = value
                self.assertEqual(self.validate(evidence)["status"], "invalid")
        evidence = synthetic_assertion()
        del evidence["actual_runtime"]
        self.assertEqual(self.validate(evidence)["status"], "invalid")
        evidence = synthetic_assertion()
        evidence["release_approved"] = True
        self.assertEqual(self.validate(evidence)["status"], "invalid")

    def test_every_check_requires_real_boolean_true(self):
        for check in CHECKS:
            for value in (False, 1, "true", None):
                with self.subTest(check=check, value=value):
                    evidence = synthetic_assertion()
                    evidence["checks"][check] = value
                    result = self.validate(evidence)
                    self.assertEqual(result["status"], "invalid")
                    self.assertIn(check, result["reason"])

    def test_runtime_and_utc_times_require_explicit_complete_fields(self):
        cases = [("google_colab_importable", False), ("google_colab_importable", 1),
                 ("runtime_marker_names", []), ("runtime_marker_names", "COLAB_RELEASE_TAG"),
                 ("runtime_marker_names", [""]), ("runtime_marker_names", ["same", "same"]),
                 ("python_version", ""), ("python_version", 312), ("runtime_version", ""),
                 ("started_at_utc", "2026-01-01T00:00:00"),
                 ("started_at_utc", "2026-01-01T00:00:00+07:00"), ("started_at_utc", "not-time")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                evidence = synthetic_assertion()
                evidence["actual_runtime"][key] = value
                self.assertEqual(self.validate(evidence)["status"], "invalid")
        evidence = synthetic_assertion()
        evidence["recorded_at_utc"] = ""
        self.assertEqual(self.validate(evidence)["status"], "invalid")

    def test_all_artifacts_and_all_100_job_step_attempts_must_stay_identical(self):
        mutations = [
            lambda e: e["after"]["artifact_hashes"].update({"summary.csv": "f" * 64}),
            lambda e: e["after"]["artifact_hashes"].pop("details.json"),
            lambda e: e["after"]["artifact_hashes"].update({"source.csv": "e" * 64}),
            lambda e: e["after"]["step_attempts"]["SYNTHETIC-TEST-JOB-000"].update(verify=2),
            lambda e: e["after"]["step_attempts"]["SYNTHETIC-TEST-JOB-000"].update(verify=1.0),
            lambda e: e["after"]["step_attempts"]["SYNTHETIC-TEST-JOB-000"].update(verify=True),
            lambda e: e["after"]["step_attempts"]["SYNTHETIC-TEST-JOB-000"].update(verify=3),
            lambda e: e["after"]["step_attempts"]["SYNTHETIC-TEST-JOB-000"].pop("calculate"),
            lambda e: e["after"]["step_attempts"].pop("SYNTHETIC-TEST-JOB-099"),
            lambda e: e["before"].update(step_attempts={}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                evidence = synthetic_assertion()
                mutate(evidence)
                self.assertEqual(self.validate(evidence)["status"], "invalid")

    def test_manual_download_receipt_actor_and_utc_time_cannot_be_inferred(self):
        for key, value in (("received", False), ("received", 1), ("actor", " "),
                           ("confirmed_at_utc", ""), ("confirmed_at_utc", "2026-01-01T00:00:00")):
            with self.subTest(key=key, value=value):
                evidence = synthetic_assertion()
                evidence["manual_download_confirmation"][key] = value
                self.assertEqual(self.validate(evidence)["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
