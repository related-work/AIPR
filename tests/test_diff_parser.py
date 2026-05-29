from __future__ import annotations

from ai_pr_review.diff_parser import (
    build_chunks,
    classify_file,
    is_binary_file,
    is_generated_file,
    is_lockfile,
    parse_diff,
)


RAW_DIFF = """diff --git a/src/app.py b/src/app.py
index 83db48f..bf269f4 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,5 +1,6 @@
 import os
+API_KEY = "abc"
 def get_user(id):
-    return db.query("select * from users where id=" + id)
+    return db.query(f"select * from users where id={id}")
 
diff --git a/docs/readme.md b/docs/readme.md
index 1111111..2222222 100644
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1,2 @@
 Hello
+World
"""


def test_parse_raw_diff_preserves_hunks_and_line_numbers() -> None:
    files = parse_diff(RAW_DIFF)

    assert [file.path for file in files] == ["src/app.py", "docs/readme.md"]
    first = files[0]
    assert first.hunks[0].old_start == 1
    assert first.hunks[0].new_start == 1
    added = [line for line in first.hunks[0].lines if line.kind == "add"]
    removed = [line for line in first.hunks[0].lines if line.kind == "remove"]
    assert added[0].new_line_no == 2
    assert removed[0].old_line_no == 3
    assert "API_KEY" in first.patch


def test_file_classification_identifies_non_code_inputs() -> None:
    assert classify_file("docs/readme.md").is_documentation
    assert is_generated_file("src/client.generated.ts")
    assert is_generated_file("schema/pb/user.pb.go")
    assert is_lockfile("package-lock.json")
    assert is_binary_file({"filename": "logo.png", "patch": None})


def test_build_chunks_skips_docs_generated_lockfiles_and_binary_files() -> None:
    files = parse_diff(RAW_DIFF + """diff --git a/package-lock.json b/package-lock.json
index 3333333..4444444 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1 +1 @@
-{}
+{"lockfileVersion": 3}
""")
    github_files = [
        {"filename": "src/app.py", "patch": files[0].patch},
        {"filename": "docs/readme.md", "patch": files[1].patch},
        {"filename": "package-lock.json", "patch": files[2].patch},
        {"filename": "assets/logo.png", "patch": None},
    ]

    chunks, limitations = build_chunks(files, github_files, changed_only=True)

    assert [chunk.path for chunk in chunks] == ["src/app.py"]
    assert any("docs/readme.md" in item for item in limitations)
    assert any("package-lock.json" in item for item in limitations)
    assert any("assets/logo.png" in item for item in limitations)
