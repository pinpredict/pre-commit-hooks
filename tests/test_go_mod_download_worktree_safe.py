"""Tests for hooks/go-mod-download-worktree-safe.sh.

A fake `go` on PATH records the directory, arguments and git environment it ran
with, so the hook's contract is checked without a network or a Go toolchain.

TheBareRepoFailure drives real git instead. Its fake `go` does what cmd/go does
on a module's first fetch, `git init --bare` in the cache directory with the
environment it inherited, which re-creates the failure this hook exists for:
on 2026-10-20 a commit from a sibling worktree turned magellan's primary
checkout bare. The control test proves the fixture reproduces it, so the test
beside it is evidence and not a tautology.

Every subprocess runs with the caller's GIT_* variables stripped. This suite is
itself a pre-commit hook in this repo, and from a worktree commit it inherits
GIT_DIR: a `git init` run with that would re-initialize THIS repository, which
is the very failure under test.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = (
    Path(__file__).resolve().parent.parent / "hooks" / "go-mod-download-worktree-safe.sh"
)

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
# Keep a developer's git config (commit signing, init templates) out of the
# repositories these tests create.
CLEAN_ENV.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

RECORDING_GO = """#!/usr/bin/env python3
import json, os, sys
keep = ("GIT_", "GOWORK")
rec = {
    "cwd": os.getcwd(),
    "argv": sys.argv[1:],
    "env": {k: v for k, v in os.environ.items() if k.startswith(keep)},
}
with open(os.environ["FAKE_GO_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\\n")
fail_in = os.environ.get("FAKE_GO_FAIL_IN")
if fail_in and os.getcwd().endswith(os.sep + fail_in):
    print("go: boom", file=sys.stderr)
    sys.exit(1)
"""

# cmd/go's first step for a module it has never fetched over git
# (newGitRepo in src/cmd/go/internal/modfetch/codehost/git.go).
INIT_BARE_GO = """#!/usr/bin/env bash
set -e
mkdir -p "$FAKE_VCS_DIR"
cd "$FAKE_VCS_DIR"
git init --bare -q
"""


def write_exe(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=CLEAN_ENV, capture_output=True, text=True, check=True
    )


class Contract(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        self.bin = Path(self._tmp.name) / "bin"
        self.log = Path(self._tmp.name) / "go.log"
        write_exe(self.bin / "go", RECORDING_GO)

    def tearDown(self):
        self._tmp.cleanup()

    def modules(self, *dirs):
        for d in dirs:
            p = self.root / d / "go.mod"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("module m\n\ngo 1.26.6\n")

    def run_hook(self, *args, env=None):
        full = dict(CLEAN_ENV, FAKE_GO_LOG=str(self.log))
        full["PATH"] = f"{self.bin}{os.pathsep}{full['PATH']}"
        full.update(env or {})
        proc = subprocess.run(
            ["bash", str(HOOK), *args],
            cwd=self.root,
            env=full,
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def called_in(self):
        return sorted(os.path.relpath(c["cwd"], self.root) for c in self.calls())

    # ── the fix ───────────────────────────────────────────────────────────
    def test_go_runs_with_the_hooks_git_location_cleared(self):
        # What git exports to a hook when the commit is made in a linked worktree.
        self.modules(".")
        rc, out = self.run_hook(env={
            "GIT_DIR": "/repo/.git/worktrees/wt",
            "GIT_INDEX_FILE": "/repo/.git/worktrees/wt/index",
            "GIT_WORK_TREE": "/wt",
            "GIT_COMMON_DIR": "/repo/.git",
            "GIT_OBJECT_DIRECTORY": "/repo/.git/objects",
        })
        self.assertEqual(rc, 0, out)
        (call,) = self.calls()
        leaked = sorted(set(call["env"]) & {
            "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY",
        })
        self.assertEqual(leaked, [], call["env"])

    def test_git_config_still_reaches_go(self):
        # The insteadOf rewrite that fetches a private module over ssh, passed
        # both ways git accepts it. Clearing it breaks the download.
        self.modules(".")
        config = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "url.git@github.com:.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/",
            "GIT_CONFIG_PARAMETERS": "'url.git@github.com:.insteadof'='https://github.com/'",
        }
        rc, out = self.run_hook(env=dict(config, GIT_DIR="/repo/.git/worktrees/wt"))
        self.assertEqual(rc, 0, out)
        (call,) = self.calls()
        for k, v in config.items():
            self.assertEqual(call["env"].get(k), v, k)

    # ── which modules, and how ────────────────────────────────────────────
    def test_every_module_downloads_in_module_mode(self):
        self.modules(".", "apps/a", "chaos")
        rc, out = self.run_hook()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.called_in(), [".", "apps/a", "chaos"])
        for c in self.calls():
            self.assertEqual(c["argv"], ["mod", "download"])
            self.assertEqual(c["env"].get("GOWORK"), "off")

    def test_vendor_and_node_modules_are_skipped(self):
        self.modules("apps/a", "apps/a/vendor/x", "web/node_modules/y")
        rc, out = self.run_hook()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.called_in(), ["apps/a"])

    def test_exclude_skips_the_module_and_everything_below_it(self):
        # magellan's apps/magellan/bench/chaos `replace`s a sibling checkout
        # that CI does not have. apps/ab shares a prefix and must still run.
        self.modules("apps/a", "apps/a/bench/x", "apps/ab")
        rc, out = self.run_hook("--exclude", "./apps/a/")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.called_in(), ["apps/ab"])

    def test_repo_without_go_mod_runs_nothing(self):
        rc, out = self.run_hook()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls(), [])

    # ── failures are loud ─────────────────────────────────────────────────
    def test_failed_download_fails_the_hook_and_names_the_module(self):
        self.modules("apps/a", "apps/b")
        rc, out = self.run_hook(env={"FAKE_GO_FAIL_IN": "apps/a"})
        self.assertEqual(rc, 1, out)
        self.assertIn("failed in apps/a", out)
        self.assertIn("go: boom", out)
        # A failure in one module does not hide the state of the others.
        self.assertEqual(self.called_in(), ["apps/a", "apps/b"])

    def test_filenames_are_rejected(self):
        # pass_filenames: true in a consumer would otherwise be ignored silently.
        self.modules(".")
        rc, out = self.run_hook("main.go")
        self.assertEqual(rc, 2, out)
        self.assertIn("unexpected argument", out)

    def test_exclude_without_a_directory_is_rejected(self):
        rc, out = self.run_hook("--exclude")
        self.assertEqual(rc, 2, out)


class TheBareRepoFailure(unittest.TestCase):
    """Real git, and a fake go that does what cmd/go does."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.main, self.wt, self.vcs = d / "main", d / "wt", d / "gomodcache" / "vcs" / "0f"
        git("-c", "init.defaultBranch=main", "init", "-q", str(self.main))
        (self.main / "go.mod").write_text("module m\n\ngo 1.26.6\n")
        git("add", "go.mod", cwd=self.main)
        git("-c", "user.name=t", "-c", "user.email=t@example.com",
            "commit", "-q", "-m", "init", cwd=self.main)
        git("worktree", "add", "-q", str(self.wt), cwd=self.main)
        wt_git_dir = git("rev-parse", "--absolute-git-dir", cwd=self.wt).stdout.strip()

        bin_dir = d / "bin"
        write_exe(bin_dir / "go", INIT_BARE_GO)
        self.hook_env = dict(
            CLEAN_ENV,
            PATH=f"{bin_dir}{os.pathsep}{CLEAN_ENV['PATH']}",
            FAKE_VCS_DIR=str(self.vcs),
            # What git exports to a hook when the commit runs in a linked worktree.
            GIT_DIR=wt_git_dir,
            GIT_INDEX_FILE=os.path.join(wt_git_dir, "index"),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def primary_core_bare(self):
        return git("config", "--get", "core.bare", cwd=self.main).stdout.strip()

    def test_control_go_fetching_inside_a_worktree_hook_turns_the_primary_bare(self):
        proc = subprocess.run(["go", "mod", "download"], cwd=self.wt, env=self.hook_env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.primary_core_bare(), "true")
        status = subprocess.run(["git", "status"], cwd=self.main, env=CLEAN_ENV,
                                capture_output=True, text=True)
        self.assertIn("must be run in a work tree", status.stderr)

    def test_hook_keeps_the_primary_checkout_a_work_tree(self):
        proc = subprocess.run(["bash", str(HOOK)], cwd=self.wt, env=self.hook_env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.primary_core_bare(), "false")
        # ...and the init landed in the module cache, where go meant it.
        self.assertTrue((self.vcs / "HEAD").is_file())
        git("status", cwd=self.main)


if __name__ == "__main__":
    unittest.main()
