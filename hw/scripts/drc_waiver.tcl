# -----------------------------------------------------------------------------
# drc_waiver.tcl - run as a TCL.PRE hook on the implementation steps
#
# It does two things, both of which have to happen INSIDE the run: launch_runs
# starts implementation as a separate Vivado process, so nothing set in the
# calling session (or the GUI's Tcl console) reaches it.
#
# The constraints file already downgrades LUTLP-1, but a DRC severity is a tool
# setting rather than a design property and does not reliably survive every
# implementation step. This hook re-applies it immediately before opt_design and
# again before write_bitstream, which are the two places the check runs.
#
# Why the check is downgraded at all, and why only for the fabric, is written
# out in constr/pynq_z2_jtag.xdc. The short version: a routing mesh has
# combinational cycles by construction, no bitstream the router emits contains
# one, and the loop nets are synthesis output so they cannot be named in advance.
# -----------------------------------------------------------------------------

# M16: implementation runs SINGLE-THREADED.
#
# route_design died inside "Phase 2.3 Update Timing" on the 12x10 fabric - no ERROR
# line, the log stopping mid-phase, the run process gone (and, run by hand from the
# placed checkpoint, Vivado itself gone). With general.maxThreads 1 the same
# checkpoint routes through. It is a threading fault in the timing engine, not a
# property of the design: the timer has to cut every combinational loop in the
# routing mesh (M16: one strongly connected component of 2146 wires, 11 270
# independent cycles) and two threads doing that concurrently is what falls over.
#
# The cost is wall-clock only (place_design measured cpu 8:29 for elapsed 6:26, so
# roughly 1.3-1.7x on implementation). 7-series caps these commands at 2 threads
# anyway. Worth retesting on a later Vivado; until then correctness wins.
set_param general.maxThreads 1
puts "drc_waiver.tcl: general.maxThreads 1 (M16: 2 threads crash route_design)"

set _top ""
catch { set _top [get_property top [current_fileset]] }

if {$_top eq "fpga4x4_top" || $_top eq "bob_top"} {
    set_property SEVERITY {Warning} [get_drc_checks LUTLP-1]
    puts "drc_waiver.tcl: LUTLP-1 downgraded to Warning for $_top"
} else {
    puts "drc_waiver.tcl: top is '$_top', LUTLP-1 left as an Error"
}
