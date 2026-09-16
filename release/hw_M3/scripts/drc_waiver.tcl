# -----------------------------------------------------------------------------
# drc_waiver.tcl - run as a TCL.PRE hook on the implementation steps
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

set _top ""
catch { set _top [get_property top [current_fileset]] }

if {$_top eq "fpga4x4_top"} {
    set_property SEVERITY {Warning} [get_drc_checks LUTLP-1]
    puts "drc_waiver.tcl: LUTLP-1 downgraded to Warning for $_top"
} else {
    puts "drc_waiver.tcl: top is '$_top', LUTLP-1 left as an Error"
}
