# -----------------------------------------------------------------------------
# probe_names.tcl - what the routed netlist calls a few fabric wires (M25 delay fix)
#
# The M25 delay_paths.rpt came back 1100 x NONET: not one u_core/u_fabric/r<node> net was
# found by name. This prints, for one sample of each class, what Vivado does have: the
# net by its RTL name, nets whose name ends like it, the hierarchical pin of the mux or
# CLB that drives it and that pin's net. Read only; a few seconds.
#
#   with the project open (Tcl console):  source E:/bob_full_v1/hw/scripts/probe_names.tcl
#   or: vivado -mode batch -source E:/bob_full_v1/hw/scripts/probe_names.tcl
# It writes probe_names.txt next to delay_paths.rpt (bob_vivado/out/<tag>/).
# -----------------------------------------------------------------------------
set script_dir [file dirname [file normalize [info script]]]
set hw_dir     [file normalize $script_dir/..]
source [file join $script_dir bob_cfg.tcl]
set cfg [bob_read_cfg $hw_dir/build.cfg]
set tag [dict get $cfg tag]
set proj_dir [file normalize [file join $hw_dir [dict get $cfg project]]]
if {[catch { current_project }]} { open_project $proj_dir/bob.xpr }
if {[catch { current_design }]} { open_run impl_1 }
set out_dir $proj_dir/out/$tag
file mkdir $out_dir
set fh [open $out_dir/probe_names.txt w]
proc say {s} { global fh; puts $s; puts $fh $s }
proc names {objs} {
    set r {}
    foreach o [lrange $objs 0 5] { lappend r [get_property NAME $o] }
    if {[llength $objs] > 6} { lappend r "... ([llength $objs] in all)" }
    return $r
}
say "design: [current_design]  top: [get_property TOP [current_design]]"
say "fabric cell: [names [get_cells -quiet u_core/u_fabric]]"
say "cells u_core/u_fabric/*: [llength [get_cells -quiet u_core/u_fabric/*]]"
say "nets  u_core/u_fabric/*: [llength [get_nets -quiet u_core/u_fabric/*]]"
say "nets  u_core/u_fabric/r*: [names [get_nets -quiet u_core/u_fabric/r*]]"
say "pins  u_core/u_fabric/m3/*: [names [get_pins -quiet u_core/u_fabric/m3/*]]"
# one sample of each class: <rr wire name> <cell or hierarchical pin that drives it>
foreach {what net pin} {
    mux_chan  r8477             u_core/u_fabric/m8477/o
    mux_ipin  r2229             u_core/u_fabric/m2229/o
    lut_out   r4706             u_core/u_fabric/u_clb_x4y8/o[6]
    xbar      u_clb_x11y6/x0[4] u_core/u_fabric/u_clb_x11y6/m0_4/o
    cout      r4700             u_core/u_fabric/u_clb_x4y8/cout
} {
    say "--- $what: $net"
    set full u_core/u_fabric/$net
    say "  get_nets exact:     [names [get_nets -quiet $full]]"
    say "  get_nets escaped:   [names [get_nets -quiet [string map {[ \\[ ] \\]} $full]]]"
    set tail [string map {[ \\[ ] \\]} [lindex [split $net /] end]]
    set h [get_nets -quiet -hierarchical -filter "NAME =~ */$tail"]
    say "  nets named */$tail: [names $h]"
    foreach n [lrange $h 0 2] { say "    [get_property NAME $n]  PARENT [get_property -quiet PARENT $n]" }
    set p [get_pins -quiet [string map {[ \\[ ] \\]} $pin]]
    say "  pin $pin: [names $p]"
    if {[llength $p]} {
        set pn [get_nets -quiet -of_objects $p]
        say "    its net: [names $pn]  PARENT [get_property -quiet PARENT [lindex $pn 0]]"
        set seg [get_nets -quiet -segments -of_objects $p]
        say "    segments: [names $seg]"
    }
}
set q [get_cells -quiet u_core/u_fabric/u_clb_x6y4/u_e1/q_reg]
say "--- ffq cell u_clb_x6y4/u_e1/q_reg: [names $q]"
say "  cells under u_clb_x6y4/u_e1: [names [get_cells -quiet u_core/u_fabric/u_clb_x6y4/u_e1/*]]"
close $fh
puts "probe_names: wrote $out_dir/probe_names.txt"
