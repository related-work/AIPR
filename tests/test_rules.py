from __future__ import annotations

from ai_pr_review.config import ReviewConfig
from ai_pr_review.diff_parser import parse_diff
from ai_pr_review.rules import run_rules


def _find(categories: set[str], findings) -> set[str]:
    return {finding.rule_id for finding in findings if finding.rule_id in categories}


def test_rules_detect_core_risks_from_diff() -> None:
    raw = """diff --git a/src/auth/service.py b/src/auth/service.py
index 1111111..2222222 100644
--- a/src/auth/service.py
+++ b/src/auth/service.py
@@ -1,8 +1,8 @@
-from auth import require_admin
 SECRET_KEY = "hardcoded-secret-value"
 def users(user_id):
-    assert response.status_code == 200
-    return query("select * from users where id=" + user_id)
+    assert response.status_code != 500
+    return query(f"select * from users where id={user_id}")
diff --git a/package.json b/package.json
index 3333333..4444444 100644
--- a/package.json
+++ b/package.json
@@ -3,6 +3,7 @@
   "dependencies": {
+    "left-pad": "1.3.0"
   }
diff --git a/src/models/user.py b/src/models/user.py
index 5555555..6666666 100644
--- a/src/models/user.py
+++ b/src/models/user.py
@@ -1,3 +1,4 @@
 class User:
+    email_verified_at = Column(DateTime)
     pass
"""
    diff_files = parse_diff(raw)
    github_files = [
        {"filename": "src/auth/service.py", "status": "modified", "patch": diff_files[0].patch},
        {"filename": "package.json", "status": "modified", "patch": diff_files[1].patch},
        {"filename": "src/models/user.py", "status": "modified", "patch": diff_files[2].patch},
    ]

    findings = run_rules(github_files, diff_files, ReviewConfig())
    found = _find(
        {
            "possible_secret",
            "sql_string_interpolation",
            "test_assertion_weakened",
            "manifest_without_lockfile",
            "auth_check_removed",
            "migration_risk",
        },
        findings,
    )

    assert found == {
        "possible_secret",
        "sql_string_interpolation",
        "test_assertion_weakened",
        "manifest_without_lockfile",
        "auth_check_removed",
        "migration_risk",
    }


def test_require_tests_for_rule_reports_missing_tests() -> None:
    raw = """diff --git a/src/payment/service.py b/src/payment/service.py
index 1111111..2222222 100644
--- a/src/payment/service.py
+++ b/src/payment/service.py
@@ -1 +1,2 @@
 def charge():
+    return True
"""
    config = ReviewConfig.from_mapping(
        {"rules": {"require_tests_for": ["src/payment/**"]}}
    )

    findings = run_rules(
        [{"filename": "src/payment/service.py", "status": "modified", "patch": "..."}],
        parse_diff(raw),
        config,
    )

    assert any(finding.rule_id == "missing_required_tests" for finding in findings)


def test_assertion_text_change_containing_not_is_not_weakened() -> None:
    raw = """diff --git a/tests/test_users.py b/tests/test_users.py
index 1111111..2222222 100644
--- a/tests/test_users.py
+++ b/tests/test_users.py
@@ -1,3 +1,3 @@
 def test_user_not_found():
-    assert response.json() == {"detail": "user not found"}
+    assert response.json() == {"detail": "User not found"}
"""

    findings = run_rules(
        [{"filename": "tests/test_users.py", "status": "modified", "patch": "..."}],
        parse_diff(raw),
        ReviewConfig(),
    )

    assert not any(finding.rule_id == "test_assertion_weakened" for finding in findings)
