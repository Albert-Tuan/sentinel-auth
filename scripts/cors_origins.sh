#!/usr/bin/env bash
# Sentinel Auth v3.3 — the CORS origin rule.
#
# ============================================================================
# WHY THIS IS ITS OWN FILE
# ============================================================================
#
# TWO deployment scripts enforce the same rule:
#
#   scripts/deploy_local.sh   — the canonical deployment
#   scripts/demo_stack.sh     — the M13 demo stack
#
# They used to carry TWO COPIES of the rule, and the copies had already
# drifted: the demo stack's error messages were shorter than the
# canonical deployment's, and the path detection was a shell glob that
# behaved differently from what its comment claimed (see below).
#
# This file is the ONE definition of "what an origin is".  It is
# SOURCED rather than executed, so it can be:
#
#   * used by both deployment scripts;
#   * exercised directly by the regression suite, with no deployment,
#     no container and no side effect.
#
# The file does NOT print anything and does NOT exit: the caller decides
# how a refusal is reported (the two scripts prefix their messages
# differently).  The reason of the FIRST offending entry is left in the
# global variable ``CORS_ERROR_MESSAGE``.
#
# ============================================================================
# WHAT AN ORIGIN IS
# ============================================================================
#
# An origin is ``scheme://host[:port]``.  Nothing more.
#
# The rule is deliberately STRICT, and it matches the application's own
# rule in ``app/cors_config.py``:
#
#   * a wildcard (``*``) is refused — a wildcard origin combined with
#     credentialed requests lets any website read authenticated
#     responses;
#   * the scheme must be ``http`` or ``https``;
#   * the host must be present;
#   * there must be NO path, NO query and NO fragment after the host —
#     a browser never sends those in an ``Origin`` header, so an entry
#     that carries one could never match anything.
#
# A single TRAILING SLASH is the one exception the application makes, and
# it makes it too: ``http://localhost:8000/`` is a common way to write an
# origin, the browser never sends the slash, and the application strips
# it so the entry still matches.  The deployment scripts therefore
# normalise it away as well, rather than refusing a spelling the
# application accepts.
#
# ============================================================================
# THE PATH DETECTION
# ============================================================================
#
# The path is detected by a slash that comes AFTER the scheme separator
# ``://``, which is what the pattern ``*://*/*`` expresses:
#
#     http://localhost:8000         -> no slash after "://"  -> ACCEPT
#     https://example.com           -> no slash after "://"  -> ACCEPT
#     http://localhost:8000/path    -> slash after "://"     -> REJECT
#     https://example.com/api       -> slash after "://"     -> REJECT
#     http://localhost:8000/path?q=1-> slash after "://"     -> REJECT
#
# The earlier pattern ``*///*`` did NOT express that.  It required two
# slashes in a row somewhere in the string, so it matched neither
# ``http://localhost:8000`` (one slash) nor ``http://localhost:8000/path``
# (two slashes, but not adjacent) — it accepted EVERY origin with a
# path, which is the opposite of what its comment claimed.  A glob
# segment may be empty, so the naive ``*/*/*`` was worse still: it
# matched a plain ``http://host`` because one of its segments was empty.
#
# The pattern below does what the comment says it does.

#: The reason the first offending entry was refused.  Empty when the
#: entry was accepted.
CORS_ERROR_MESSAGE=""

# =============================================================================
# The rule
# =============================================================================

#: Check one allow-list entry.
#:
#: Returns 0 when the entry is a usable origin and 1 when it is not.
#: On a refusal, the reason is left in ``CORS_ERROR_MESSAGE``.
#:
#: Usage:
#:
#:     check_cors_origin_entry "http://localhost:8000"
check_cors_origin_entry() {
    local entry="$1"

    CORS_ERROR_MESSAGE=""

    if [ "${entry}" = "*" ]; then
        CORS_ERROR_MESSAGE="CORS_ALLOWED_ORIGINS must not contain '*': a wildcard origin lets any website read authenticated responses. List the exact origins instead."
        return 1
    fi

    case "${entry}" in
        http://*|https://*) ;;
        *)
            CORS_ERROR_MESSAGE="CORS_ALLOWED_ORIGINS entry '${entry}' is not a full origin. Use scheme://host[:port]."
            return 1
            ;;
    esac

    # The host must be present.  "http://" has a scheme but no host, and
    # it could never match an Origin header.
    local authority="${entry#*://}"
    case "${authority}" in
        ""|/*)
            CORS_ERROR_MESSAGE="CORS_ALLOWED_ORIGINS entry '${entry}' has no host. Use scheme://host[:port]."
            return 1
            ;;
    esac

    # A single trailing slash is a common spelling of an origin and is
    # harmless — the browser never sends it.  It is normalised away
    # rather than refused, so the deployment accepts exactly what the
    # application accepts.
    case "${entry}" in
        */) entry="${entry%/}" ;;
    esac

    # The path, the query and the fragment are detected AFTER the scheme
    # separator.  The patterns are anchored on "://", so the separator
    # itself can never be mistaken for a path.
    case "${entry}" in
        *://*/*)
            CORS_ERROR_MESSAGE="CORS_ALLOWED_ORIGINS entry '${entry}' must be an origin without a path. Use scheme://host[:port]."
            return 1
            ;;
    esac

    # The "?" is ESCAPED: in a shell pattern an unescaped "?" means "any
    # single character", so an unescaped one would match EVERY origin.
    case "${entry}" in
        *://*\?*)
            CORS_ERROR_MESSAGE="CORS_ALLOWED_ORIGINS entry '${entry}' must be an origin without a query string. Use scheme://host[:port]."
            return 1
            ;;
    esac

    case "${entry}" in
        *://*\#*)
            CORS_ERROR_MESSAGE="CORS_ALLOWED_ORIGINS entry '${entry}' must be an origin without a fragment. Use scheme://host[:port]."
            return 1
            ;;
    esac

    return 0
}

#: Check a whole comma-separated allow-list.
#:
#: Returns 0 when every entry is usable and 1 when at least one is not.
#: The reason of the FIRST offending entry is left in
#: ``CORS_ERROR_MESSAGE``.
#:
#: An EMPTY list is accepted — it means "no cross-origin access at all",
#: which is a valid and strict configuration.
#:
#: Usage:
#:
#:     check_cors_allow_list "http://localhost:8000,https://soc.example.com"
check_cors_allow_list() {
    local raw="$1"
    local entry

    CORS_ERROR_MESSAGE=""

    for entry in $(printf '%s' "${raw}" | tr ',' ' '); do
        entry="$(printf '%s' "${entry}" | tr -d '[:space:]')"
        [ -n "${entry}" ] || continue
        if ! check_cors_origin_entry "${entry}"; then
            return 1
        fi
    done

    return 0
}
