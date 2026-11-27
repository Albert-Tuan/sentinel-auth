"""The CORS origin rule of the deployment scripts.

``scripts/deploy_local.sh`` (the canonical deployment) and
``scripts/demo_stack.sh`` (the M13 demo stack) both refuse a CORS
allow-list entry that is not a usable origin.  The rule itself lives in
``scripts/cors_origins.sh``, which is SOURCED by both scripts — so this
suite exercises the very code the deployments run, with no deployment,
no container and no side effect.

Why the suite exists
--------------------

The rule used to be a shell glob, ``*///*``, that was supposed to match
"a ``/`` after ``scheme://host``".  It did not: it required two
adjacent slashes, so it accepted ``http://localhost:8000/path`` — the
exact case it was written to refuse.  A glob segment may also be empty,
so the naive ``*/*/*`` would have matched a plain ``http://host``.

A rule that silently accepts what it must refuse is worse than no rule
at all, because it is believed to be there.

The three layers
----------------

*   **The rule** — the cases below, exactly as they must behave.
*   **The wiring** — both deployment scripts really source the shared
    rule, and neither carries a private copy of it any more.
*   **The agreement** — the shell rule and the application's own rule
    in ``app/cors_config.py`` accept and refuse the same entries, so a
    configuration the deployment accepts is a configuration the
    application accepts.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

CORS_RULE_SCRIPT = SCRIPTS_DIR / "cors_origins.sh"
DEPLOY_SCRIPT = SCRIPTS_DIR / "deploy_local.sh"
DEMO_STACK_SCRIPT = SCRIPTS_DIR / "demo_stack.sh"


def _check_entry(entry: str) -> tuple[bool, str]:
    """Run the shared rule on one entry.

    Returns ``(accepted, reason)``.  The reason is empty when the entry
    was accepted.
    """
    script = (
        f'source "{CORS_RULE_SCRIPT}"\n'
        f'if check_cors_origin_entry "{entry}"; then\n'
        "  printf 'ACCEPTED'\n"
        "else\n"
        "  printf 'REFUSED:%s' \"${CORS_ERROR_MESSAGE}\"\n"
        "fi\n"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout
    if output.startswith("ACCEPTED"):
        return True, ""
    assert output.startswith("REFUSED:"), output
    return False, output[len("REFUSED:"):]


def _check_allow_list(raw: str) -> tuple[bool, str]:
    """Run the shared rule on a whole allow-list."""
    script = (
        f'source "{CORS_RULE_SCRIPT}"\n'
        f'if check_cors_allow_list "{raw}"; then\n'
        "  printf 'ACCEPTED'\n"
        "else\n"
        "  printf 'REFUSED:%s' \"${CORS_ERROR_MESSAGE}\"\n"
        "fi\n"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout
    if output.startswith("ACCEPTED"):
        return True, ""
    assert output.startswith("REFUSED:"), output
    return False, output[len("REFUSED:"):]


# =============================================================================
# The rule
# =============================================================================

class TestTheCorsOriginRule:
    """The cases the review named, one test each."""

    @pytest.mark.parametrize(
        "entry",
        [
            "http://localhost:8000",
            "https://example.com",
        ],
    )
    def test_a_plain_origin_is_accepted(self, entry):
        accepted, reason = _check_entry(entry)
        assert accepted, f"'{entry}' must be accepted, but it was refused: {reason}"

    @pytest.mark.parametrize(
        "entry",
        [
            "http://localhost:8000/path",
            "https://example.com/api",
            "http://localhost:8000/path?q=1",
        ],
    )
    def test_an_origin_with_a_path_is_refused(self, entry):
        accepted, reason = _check_entry(entry)
        assert not accepted, (
            f"'{entry}' carries a path and must be refused, but it was accepted"
        )
        assert "path" in reason, (
            f"the refusal must name the path as the reason: {reason}"
        )

    def test_the_wildcard_is_refused(self):
        accepted, reason = _check_entry("*")
        assert not accepted, "the wildcard origin must be refused"
        assert "*" in reason

    def test_the_path_detection_is_anchored_on_the_scheme_separator(self):
        """The regression the whole file exists for.

        The old pattern was ``*///*``, which required two ADJACENT
        slashes.  ``http://localhost:8000/path`` has two slashes but
        they are not adjacent, so the old pattern accepted it — the
        opposite of what it was written to do.
        """
        for entry in (
            "http://localhost:8000/path",
            "https://example.com/api",
            "http://localhost:8000/path?q=1",
        ):
            accepted, _ = _check_entry(entry)
            assert not accepted, (
                f"'{entry}' must be refused by the path detection"
            )

    def test_a_plain_origin_is_not_mistaken_for_one_with_a_path(self):
        """The other half of the same regression.

        A glob segment may be empty, so the naive ``*/*/*`` matched
        ``http://host`` and would have refused every legitimate origin.
        """
        for entry in ("http://localhost:8000", "https://example.com"):
            accepted, reason = _check_entry(entry)
            assert accepted, (
                f"'{entry}' is a plain origin and must be accepted, but it "
                f"was refused: {reason}"
            )

    @pytest.mark.parametrize(
        "entry",
        [
            "soc.example.com",          # no scheme
            "ftp://soc.example.com",    # an unsupported scheme
            "http://",                  # no host
            "https://example.com/?x=1",  # a query
            "https://example.com#frag",   # a fragment
        ],
    )
    def test_an_unusable_entry_is_refused(self, entry):
        accepted, reason = _check_entry(entry)
        assert not accepted, f"'{entry}' must be refused, but it was accepted"
        assert reason, "a refusal must say why"

    def test_a_trailing_slash_is_normalised_away(self):
        """The application accepts a trailing slash, so the deployment must.

        ``app/cors_config.py`` strips a single trailing slash so the
        entry still matches an ``Origin`` header.  A deployment that
        refused the same spelling would refuse a configuration the
        application considers valid.
        """
        accepted, reason = _check_entry("http://localhost:8000/")
        assert accepted, (
            "a trailing slash is a common spelling of an origin and must be "
            f"accepted, but it was refused: {reason}"
        )

    def test_a_whole_allow_list_is_accepted(self):
        accepted, reason = _check_allow_list(
            "http://localhost:8000,https://example.com,https://soc.example.com"
        )
        assert accepted, reason

    def test_one_bad_entry_refuses_the_whole_list(self):
        accepted, reason = _check_allow_list(
            "http://localhost:8000,http://localhost:8000/path"
        )
        assert not accepted
        assert "http://localhost:8000/path" in reason

    def test_an_empty_list_is_accepted(self):
        """An empty allow-list means "no cross-origin access at all"."""
        accepted, reason = _check_allow_list("")
        assert accepted, reason

    def test_the_whitespace_around_an_entry_is_ignored(self):
        accepted, reason = _check_allow_list(" http://localhost:8000 , https://example.com ")
        assert accepted, reason


# =============================================================================
# The wiring
# =============================================================================

class TestBothDeploymentScriptsUseTheSharedRule:
    """Neither script may carry a private copy of the rule any more."""

    def _source(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "script",
        [DEPLOY_SCRIPT, DEMO_STACK_SCRIPT],
        ids=["deploy_local", "demo_stack"],
    )
    def test_the_script_sources_the_shared_rule(self, script):
        source = self._source(script)
        assert 'source "${REPO_ROOT}/scripts/cors_origins.sh"' in source, (
            f"{script.name} must source the shared CORS rule"
        )

    @pytest.mark.parametrize(
        "script",
        [DEPLOY_SCRIPT, DEMO_STACK_SCRIPT],
        ids=["deploy_local", "demo_stack"],
    )
    def test_the_script_has_no_private_path_glob_any_more(self, script):
        source = self._source(script)
        assert "*///*" not in source, (
            f"{script.name} still carries the broken path glob '*///*', which "
            "accepts every origin that has a path"
        )

    @pytest.mark.parametrize(
        "script",
        [DEPLOY_SCRIPT, DEMO_STACK_SCRIPT],
        ids=["deploy_local", "demo_stack"],
    )
    def test_the_script_calls_the_shared_check(self, script):
        source = self._source(script)
        assert "check_cors_allow_list" in source, (
            f"{script.name} must call check_cors_allow_list"
        )

    @pytest.mark.parametrize(
        "script",
        [DEPLOY_SCRIPT, DEMO_STACK_SCRIPT],
        ids=["deploy_local", "demo_stack"],
    )
    def test_the_script_is_syntactically_valid(self, script):
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_the_shared_rule_is_syntactically_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(CORS_RULE_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_the_shared_rule_defines_both_functions(self):
        source = self._source(CORS_RULE_SCRIPT)
        assert re.search(r"^check_cors_origin_entry\(\)", source, re.M)
        assert re.search(r"^check_cors_allow_list\(\)", source, re.M)


# =============================================================================
# The agreement with the application
# =============================================================================

class TestTheShellRuleAndTheApplicationAgree:
    """A configuration the deployment accepts must be one the app accepts.

    ``app/cors_config.py`` is the authority at RUNTIME; the shell rule
    is the authority at DEPLOY time.  If they disagreed, a deployment
    could be accepted and then start an application that refuses to
    boot — or worse, one that accepts a wildcard.
    """

    @pytest.mark.parametrize(
        "entry",
        [
            "http://localhost:8000",
            "https://example.com",
            "http://localhost:8000/path",
            "https://example.com/api",
            "http://localhost:8000/path?q=1",
            "*",
            "soc.example.com",
            "http://localhost:8000/",
        ],
    )
    def test_both_rules_agree(self, entry):
        from app import cors_config

        shell_accepted, _ = _check_entry(entry)

        try:
            cors_config.parse_cors_origins(entry)
            app_accepted = True
        except cors_config.CORSConfigurationError:
            app_accepted = False

        assert shell_accepted == app_accepted, (
            f"the shell rule and the application disagree about '{entry}': "
            f"shell={'accept' if shell_accepted else 'refuse'}, "
            f"application={'accept' if app_accepted else 'refuse'}"
        )

    def test_the_default_allowlist_passes_the_shell_rule(self):
        """The origins the application ships with must survive the
        deployment's own check — otherwise the default deployment would
        refuse its own default configuration."""
        from app import cors_config

        raw = ",".join(cors_config.default_cors_origins())
        accepted, reason = _check_allow_list(raw)
        assert accepted, (
            "the application's default allow-list must pass the deployment's "
            f"own rule, but it was refused: {reason}"
        )

    def test_the_demo_stack_allowlist_passes_the_shell_rule(self):
        """The origins the demo stack configures must survive the check.

        The TRACKED example file is the source of truth here, not the
        operator's ``.env.demo``: the example is committed, so this
        assertion runs everywhere, and a skip would be a hole in the
        coverage — which the CI acceptance policy treats as a failure.
        The operator's own file may name other origins, and those are
        validated by the demo stack itself when it starts.
        """
        demo_env = REPO_ROOT / ".env.demo.example"
        if not demo_env.exists():
            pytest.fail(
                "the tracked demo environment example is missing, so the "
                "demo allow-list cannot be checked"
            )

        raw = None
        for line in demo_env.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("CORS_ALLOWED_ORIGINS="):
                raw = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                break

        assert raw, (
            "the tracked demo environment example configures no allow-list"
        )

        accepted, reason = _check_allow_list(raw)
        assert accepted, (
            f"the demo allow-list '{raw}' must pass the deployment's own "
            f"rule, but it was refused: {reason}"
        )
