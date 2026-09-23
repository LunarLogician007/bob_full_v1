# -----------------------------------------------------------------------------
# place_report.tcl - TCL.POST hook on place_design (M21)
#
# The M21 builds each spent hours in phys_opt_design before anyone could see which
# clock was failing: the log only prints an overall WNS and the nets phys_opt tries.
# Right after placement this prints the worst path of each clock into runme.log and
# writes a short timing summary beside it (impl_1/bob_top_timing_placed.rpt). If a
# clock is hundreds of ns negative, stop the run and send both.
# -----------------------------------------------------------------------------
foreach grp {sysclk tck} {
    set p [get_timing_paths -quiet -max_paths 1 -nworst 1 -group $grp]
    if {[llength $p] == 0} {
        puts "place_report: $grp: no timed path"
        continue
    }
    puts [format "place_report: %-6s WNS %s ns  requirement %s ns  from %s  to %s" $grp \
        [get_property SLACK $p] [get_property REQUIREMENT $p] \
        [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p]]
}
report_timing_summary -quiet -max_paths 5 -file bob_top_timing_placed.rpt
