#!/usr/bin/env bash
# Shared process lookup for the wildlife cameras.  source this, do not run it.
#
# WHY THIS EXISTS
# ---------------
# `pgrep -f some_script.py` matches ANY process whose command line contains
# that text: the shell running the check, a terminal where someone typed the
# name, an editor with the file open, even the pgrep pipeline itself. That is
# not a theoretical worry - it made check_camera.sh believe a feed was running
# and silently skip its capture test, which is the single most important thing
# that file does.
#
# So confirm each candidate really is an interpreter running the script, rather
# than something merely mentioning it.

# script_pid <script-name> [required-arg]
#   Echo the PID of a python process running <script-name>, optionally also
#   requiring <required-arg> on its command line. Echoes nothing if none.
script_pid() {
    local want="$1" need="${2:-}" pid exe cmd
    for pid in $(pgrep -f "$want" 2>/dev/null); do
        # Never match this shell or its parent.
        [ "$pid" = "$$" ] && continue
        [ "$pid" = "$PPID" ] && continue
        exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null) || continue
        # A shell that merely mentions the name is not the process we want.
        case "$exe" in *python*) ;; *) continue ;; esac
        cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null) || continue
        case "$cmd" in *"$want"*) ;; *) continue ;; esac
        if [ -n "$need" ]; then
            case "$cmd" in *"$need"*) ;; *) continue ;; esac
        fi
        printf '%s\n' "$pid"
        return 0
    done
    return 1
}
