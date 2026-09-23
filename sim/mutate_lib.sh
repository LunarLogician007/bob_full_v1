# Shared by the mutation suites (sim/mutate_*.sh); sourced, not run.
#
# M21: some mutants (xbar-sel-off-by-one, mux-inputs-shifted) wire the fabric into a
# combinational loop, and a zero-delay loop spins in vvp forever; the suites used to
# hang on them. Every simulation now runs under a watchdog, MUTATE_TIMEOUT seconds
# (default 2700: a normal tb_bob run is 443 s alone, slower 4 at a time), and a mutant with no verdict by then
# counts as killed: the unmutated design never hangs, so the benches did tell it apart.
# The report says "hang" so nobody mistakes it for a failed check. There is no
# `timeout` on macOS, hence the background kill.

MUTATE_TIMEOUT=${MUTATE_TIMEOUT:-2700}

# vvp_verdict <dir> <file.vvp>: run the simulation in <dir> and print
#   pass   the bench printed ALL TESTS PASSED
#   fail   it finished without it
#   hang   no end within MUTATE_TIMEOUT seconds (killed)
vvp_verdict() {
    local dir=$1 vvp=$2
    local log="$dir/$vvp.log" flag="$dir/$vvp.hang"
    rm -f "$flag"
    (cd "$dir" && exec vvp "$vvp") > "$log" 2>&1 &
    local pid=$!
    (
        trap 'kill "$s" 2>/dev/null; exit 0' TERM
        sleep "$MUTATE_TIMEOUT" & s=$!
        wait "$s"
        if kill -0 "$pid" 2>/dev/null; then : > "$flag"; kill -9 "$pid" 2>/dev/null; fi
    ) >/dev/null 2>&1 &               # off the caller's $(...) pipe, or it would wait for the sleep
    local dog=$!
    wait "$pid" 2>/dev/null
    kill "$dog" 2>/dev/null; wait "$dog" 2>/dev/null
    if [[ -e "$flag" ]]; then echo hang
    elif grep -q 'ALL TESTS PASSED' "$log"; then echo pass
    else echo fail; fi
}

# killed_note <verdict>: the suffix a killed mutant's line gets for a hang
killed_note() {
    [[ $1 == hang ]] && echo " (hang: no verdict in ${MUTATE_TIMEOUT} s, killed)"
}
