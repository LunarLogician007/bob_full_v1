# -----------------------------------------------------------------------------
# extract_delays.tcl - the fabric's per-element delays on THIS implementation (M20)
#
# Sourced by build.tcl after implementation, with the routed design open. It times the
# hops listed in delay_samples.txt (written on the Mac by software/bob/delays.py plan:
# a reproducible random sample of every element class) and writes every report, one
# per sample, to $out_dir/delay_paths.rpt. On the Mac
#     software/bob/delays.py fold docs/reports/M20/delay_paths.rpt
# turns them into software/bob/delays.json, which software/bob/timing.py uses to give
# each guest design its own user clock.
#
# A sample line is "<class> <from> <to>":
#   mux_chan / mux_ipin / lut / carry   two rr-wire nets (u_core/u_fabric/r<node>):
#        the worst path through both; the hop is arrival(to) - arrival(from)
#   ffq  <q_reg cell> <O net>   clock-to-Q of a CLB flip-flop onto its output wire
#   ffd  <I net> <q_reg cell>   from a CLB input wire to its flip-flop's D, with setup
#
# The fabric is loop-ridden when unconfigured, and Vivado cuts loops by disabling arcs,
# so some samples have no path at all; they are written as "### ... NOPATH" and the
# fold counts them. No sample changes the design: this only reads timing.
# -----------------------------------------------------------------------------
set samples [file join [file dirname [info script]] delay_samples.txt]
if {![file exists $samples]} {
    puts "extract_delays: no $samples - run software/bob/delays.py plan on the Mac; skipped"
    return
}
set out [file join $out_dir delay_paths.rpt]
set fh [open $out w]
set sf [open $samples r]
set lines [split [read $sf] "\n"]
close $sf
set n 0; set miss 0; set t0 [clock seconds]
foreach line $lines {
    set line [string trim $line]
    if {$line eq "" || [string index $line 0] eq "#"} { continue }
    lassign $line cls a b
    incr n
    set s ""
    set err [catch {
        switch -- $cls {
            ffq     { set s [report_timing -quiet -from [get_cells -quiet $a] -through [get_nets -quiet $b] \
                             -delay_type max -max_paths 1 -input_pins -return_string] }
            ffd     { set s [report_timing -quiet -through [get_nets -quiet $a] -to [get_cells -quiet $b] \
                             -delay_type max -max_paths 1 -input_pins -return_string] }
            default { set s [report_timing -quiet -through [get_nets -quiet $a] -through [get_nets -quiet $b] \
                             -delay_type max -max_paths 1 -input_pins -return_string] }
        }
    } msg]
    if {$err || ![string match "*Slack*" $s]} {
        incr miss
        puts $fh "### $cls $a $b NOPATH"
        continue
    }
    puts $fh "### $cls $a $b"
    puts $fh $s
    if {$n % 100 == 0} { puts "extract_delays: $n samples, [expr {[clock seconds] - $t0}] s" }
}
close $fh
puts "extract_delays: $n samples ($miss without a path) in [expr {[clock seconds] - $t0}] s -> $out"
