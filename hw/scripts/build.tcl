# -----------------------------------------------------------------------------
# build.tcl - adaptable Vivado flow for bob_full_v1
#
# Copy the whole hw/ folder to the Vivado machine (paste over the old copy) and:
#
#   vivado -mode batch -source <path>/hw/scripts/build.tcl                 build
#   vivado -mode batch -source <path>/hw/scripts/build.tcl -tclargs all    build + program
#   ... -tclargs program     program the last bitstream built for this tag
#   ... -tclargs force       rebuild even if nothing changed
#   ... -tclargs sim         XSim behavioural simulation of sim_top
#   ... -tclargs status      show what would be added/removed/rebuilt; change nothing
#
# key=value arguments override hw/build.cfg, e.g.  -tclargs all top=mini_fpga_top
#
# What makes it adaptable:
#   - the project lives OUTSIDE hw/ (build.cfg 'project', default ../bob_vivado),
#     so pasting a new hw/ never deletes it
#   - an existing project is opened, never re-created
#   - the project's file lists are synced to hw/sources.f and build.cfg: new files
#     are added, files no longer listed are removed (works even if hw/ was pasted
#     to a different place - the old paths drop out, the new ones go in)
#   - a content fingerprint of every input decides whether to rebuild
#
# Carried over from bob/vivado/create_project.tcl (hardware-proven): one Vivado
# session for everything, explicit run-status checks (launch_runs does not raise),
# the LUTLP-1 hooks, and WNS handling that tolerates an empty value.
# -----------------------------------------------------------------------------

set script_dir [file normalize [file dirname [info script]]]
set hw_dir     [file normalize $script_dir/..]

# --- small helpers (plain Tcl, no Vivado calls) -----------------------------

proc bob_strip_comment {line} {
    set i [string first "#" $line]
    if {$i >= 0} { set line [string range $line 0 [expr {$i - 1}]] }
    return [string trim $line]
}

# build.cfg -> dict
proc bob_read_cfg {path} {
    set cfg [dict create]
    set fh [open $path r]
    foreach line [split [read $fh] "\n"] {
        set line [bob_strip_comment $line]
        if {$line eq ""} continue
        set eq [string first "=" $line]
        if {$eq < 0} { error "build.cfg: no '=' in line: $line" }
        dict set cfg [string trim [string range $line 0 [expr {$eq - 1}]]] \
                     [string trim [string range $line [expr {$eq + 1}] end]]
    }
    close $fh
    return $cfg
}

# sources.f -> list of absolute, normalised paths (must exist)
proc bob_read_list {path base} {
    set out {}
    set fh [open $path r]
    foreach line [split [read $fh] "\n"] {
        set line [bob_strip_comment $line]
        if {$line eq ""} continue
        set f [file normalize [file join $base $line]]
        if {![file exists $f]} { error "[file tail $path]: missing file $f" }
        lappend out $f
    }
    close $fh
    return $out
}

# 32-bit FNV-1a over file contents, in pure Tcl (Vivado's Tcl has no md5).
# Content-based on purpose: a copy to another machine changes every mtime.
proc bob_fingerprint {files extra} {
    set h 2166136261
    foreach f [concat [lsort $files]] {
        set fh [open $f r]
        fconfigure $fh -translation binary
        set data [read $fh]
        close $fh
        # normalise CRLF so a Windows checkout does not force a rebuild
        set data [string map [list "\r\n" "\n"] $data]
        binary scan "[file tail $f]\0$data" cu* bytes
        foreach b $bytes {
            set h [expr {(($h ^ $b) * 16777619) & 0xFFFFFFFF}]
        }
    }
    binary scan $extra cu* bytes
    foreach b $bytes {
        set h [expr {(($h ^ $b) * 16777619) & 0xFFFFFFFF}]
    }
    return [format %08x $h]
}

# (want, have) -> {to_add to_remove}
proc bob_diff {want have} {
    set add {}
    set rm  {}
    foreach f $want { if {[lsearch -exact $have $f] < 0} { lappend add $f } }
    foreach f $have { if {[lsearch -exact $want $f] < 0} { lappend rm  $f } }
    return [list $add $rm]
}

# --- arguments ----------------------------------------------------------------

# Vivado GUI (Tools > Run Tcl Script) cannot pass -tclargs. There, type in the
# Tcl Console instead:
#     set bob_args {all}
#     source C:/bob/bob_full_v1/hw/scripts/build.tcl
# bob_args is used once and cleared, so a later plain "Run Tcl Script" builds.
set in_gui [expr {[info exists ::rdi::mode] && $::rdi::mode eq "gui"}]
set bob_argv {}
if {[info exists ::bob_args]} {
    set bob_argv $::bob_args
    unset ::bob_args
} elseif {!$in_gui && [info exists argv]} {
    set bob_argv $argv
}

set action "build"
set overrides [dict create]
if {1} {
    foreach a $bob_argv {
        if {[string first "=" $a] > 0} {
            set eq [string first "=" $a]
            dict set overrides [string range $a 0 [expr {$eq - 1}]] \
                               [string range $a [expr {$eq + 1}] end]
        } else {
            set action $a
        }
    }
}
if {[lsearch -exact {build all program force sim status} $action] < 0} {
    error "unknown action '$action' - expected build, all, program, force, sim or status"
}

set cfg [dict merge [bob_read_cfg $hw_dir/build.cfg] $overrides]
foreach key {tag top part xdc project} {
    if {![dict exists $cfg $key]} { error "build.cfg: missing '$key'" }
}
set tag      [dict get $cfg tag]
set top      [dict get $cfg top]
set part     [dict get $cfg part]
set jobs     [expr {[dict exists $cfg jobs] ? [dict get $cfg jobs] : 4}]
# Plain if/else, not expr: expr would turn "00000002" into 2 (and an invalid
# octal like "00000009" into an error).
set idcode   ""
set usercode ""
if {[dict exists $cfg idcode]}   { set idcode   [dict get $cfg idcode] }
if {[dict exists $cfg usercode]} { set usercode [dict get $cfg usercode] }
# IDCODE/USERCODE in build.cfg belong to the configured top; a top= override on
# the command line without idcode=/usercode= keeps that top's own RTL defaults
if {[dict exists $overrides top] && ![dict exists $overrides idcode]}   { set idcode "" }
if {[dict exists $overrides top] && ![dict exists $overrides usercode]} { set usercode "" }

set proj_dir [file normalize [file join $hw_dir [dict get $cfg project]]]
set proj_name bob
set xpr      $proj_dir/$proj_name.xpr
set out_dir  $proj_dir/out/$tag
set bitfile  $out_dir/$top.bit
set stampf   $proj_dir/bob_build.stamp

set src_files [bob_read_list $hw_dir/sources.f $hw_dir]
set xdc_files [list [file normalize $hw_dir/[dict get $cfg xdc]]]
set sim_files {}
if {[dict exists $cfg sim_files]} {
    foreach f [dict get $cfg sim_files] {
        set p [file normalize $hw_dir/$f]
        if {![file exists $p]} { error "build.cfg sim_files: missing $p" }
        lappend sim_files $p
    }
}
set waiver $script_dir/drc_waiver.tcl

puts ""
puts "action   : $action"
puts "tag      : $tag"
puts "top      : $top"
# NB: never build a display string with expr - "0x3BEEF093" is a number to expr
# and comes back as 1005514899.
if {$idcode ne ""} { set idcode_txt "0x[string toupper $idcode]" } else { set idcode_txt "(RTL default)" }
puts "idcode   : $idcode_txt"
if {$usercode ne ""} { set usercode_txt "0x[string toupper $usercode]" } else { set usercode_txt "(RTL default)" }
puts "usercode : $usercode_txt"
puts "hw       : $hw_dir"
puts "project  : $xpr"
puts "outputs  : $out_dir"
puts ""

# Anything left open from an earlier source in the same session would collide.
# (In the GUI this also closes the project a previous run left open - it is
# reopened just below, so nothing is lost.)
catch { close_project }

# --- programming --------------------------------------------------------------

proc program_board {bitfile} {
    if {![file exists $bitfile]} {
        error "no bitstream at $bitfile - build this tag first"
    }
    open_hw_manager
    connect_hw_server
    open_hw_target

    # The Zynq chain holds the ARM DAP as well as the FPGA; pick the FPGA.
    set dev ""
    foreach d [get_hw_devices] {
        if {[string match "xc7z020*" $d]} { set dev $d ; break }
    }
    if {$dev eq ""} {
        error "no xc7z020 on the JTAG chain - devices: [get_hw_devices]"
    }
    puts "programming $dev with $bitfile"

    current_hw_device $dev
    refresh_hw_device -update_hw_probes false $dev
    set_property PROGRAM.FILE $bitfile $dev
    program_hw_devices $dev
    refresh_hw_device $dev
    close_hw_manager

    puts ""
    puts "DONE bitstream loaded. Configuration is volatile - re-run with"
    puts "     -tclargs program after every power cycle."
}

if {$action eq "program"} {
    program_board $bitfile
    return
}

# --- status: report only, never create or modify -----------------------------

proc bob_fileset_files {fs} {
    set have {}
    foreach f [get_files -quiet -of_objects [get_filesets $fs]] {
        lappend have [file normalize $f]
    }
    return $have
}

# Included headers are not in sources.f but change the design: fingerprint them too.
set fp [bob_fingerprint [concat $src_files $xdc_files $waiver [glob -nocomplain $hw_dir/src/generated/*.vh]] \
                        "top=$top idcode=$idcode usercode=$usercode part=$part"]

if {$action eq "status"} {
    if {![file exists $xpr]} {
        puts "no project yet - 'build' would create $xpr"
        puts "and add [llength $src_files] sources, [llength $xdc_files] constraints, [llength $sim_files] testbenches"
        return
    }
    open_project $xpr
    foreach {fs want} [list sources_1 $src_files constrs_1 $xdc_files sim_1 $sim_files] {
        lassign [bob_diff $want [bob_fileset_files $fs]] add rm
        if {$fs eq "sim_1"} {
            # sim_1 may list design sources too; never treat those as stale
            set keep {}
            foreach f $rm { if {[lsearch -exact $src_files $f] < 0} { lappend keep $f } }
            set rm $keep
        }
        foreach f $add { puts "  $fs  + $f" }
        foreach f $rm  { puts "  $fs  - $f" }
    }
    set old ""
    if {[file exists $stampf]} { set fh [open $stampf r]; set old [string trim [read $fh]]; close $fh }
    puts ""
    puts "fingerprint now $fp, last build [expr {$old eq "" ? "none" : $old}]"
    puts [expr {$fp eq $old ? "build would be skipped (up to date)" : "build would rebuild"}]
    close_project
    return
}

# --- create or reuse ----------------------------------------------------------

file mkdir $proj_dir
if {[file exists $xpr]} {
    puts "reusing existing project"
    open_project $xpr
} else {
    puts "creating project"
    create_project $proj_name $proj_dir -part $part
    set_property target_language Verilog [current_project]
}
if {[get_property PART [current_project]] ne $part} {
    set_property PART $part [current_project]
}

# --- sync the file lists --------------------------------------------------------

set changed 0
foreach {fs want} [list sources_1 $src_files constrs_1 $xdc_files sim_1 $sim_files] {
    lassign [bob_diff $want [bob_fileset_files $fs]] add rm
    if {$fs eq "sim_1"} {
        set keep {}
        foreach f $rm { if {[lsearch -exact $src_files $f] < 0} { lappend keep $f } }
        set rm $keep
    }
    foreach f $rm {
        puts "  $fs  - $f"
        if {[catch { remove_files -fileset $fs $f } err]} {
            puts "  WARNING: could not remove $f from $fs: $err"
        }
        set changed 1
    }
    if {[llength $add]} {
        foreach f $add { puts "  $fs  + $f" }
        add_files -fileset $fs -norecurse $add
        set changed 1
    }
}
if {!$changed} { puts "file lists already match sources.f / build.cfg" }

# clb_pkg.sv / lut6.sv / clb.sv are SystemVerilog; mark them or the package
# will not elaborate.
set svfiles [get_files -quiet *.sv]
if {[llength $svfiles]} { set_property file_type SystemVerilog $svfiles }

set_property top $top [get_filesets sources_1]
set generics {}
if {$idcode ne ""}   { lappend generics "IDCODE_VALUE=32'h$idcode" }
if {$usercode ne ""} { lappend generics "USERCODE_VALUE=32'h$usercode" }
set_property generic [join $generics " "] [get_filesets sources_1]

if {[dict exists $cfg sim_top]} {
    set_property top [dict get $cfg sim_top] [get_filesets sim_1]
}
# bob_params.vh (generated by software/bob/device.py) is `included by the RTL
set_property include_dirs [list [file normalize $hw_dir/src/generated]] [get_filesets sources_1]
set_property include_dirs [list [file normalize $hw_dir/tb] [file normalize $hw_dir/src/generated]] [get_filesets sim_1]
if {[dict exists $cfg sim_defines]} {
    # both tops select a plain wire instead of a BUFG under SIMULATION
    set_property verilog_define [dict get $cfg sim_defines] [get_filesets sim_1]
}

update_compile_order -fileset sources_1
update_compile_order -fileset sim_1

# The fabric trips LUTLP-1 by construction - see constr/pynq_z2.xdc. Re-point
# the hooks on every run: hw/ may have been pasted somewhere new.
# ROUTE_DESIGN too, from M16: the hook also forces general.maxThreads 1, and a
# parameter has to be set in the process that runs the step (all impl steps share
# one process, so opt_design's hook already covers it - this is belt and braces in
# case a future flow splits them).
set_property STEPS.OPT_DESIGN.TCL.PRE      $waiver [get_runs impl_1]
set_property STEPS.ROUTE_DESIGN.TCL.PRE    $waiver [get_runs impl_1]
set_property STEPS.WRITE_BITSTREAM.TCL.PRE $waiver [get_runs impl_1]
# M21: the worst path of each clock, printed right after placement (place_report.tcl),
# so a failing build says which clock it is before phys_opt spends hours on it.
set_property STEPS.PLACE_DESIGN.TCL.POST $script_dir/place_report.tcl [get_runs impl_1]

# M7: the generated fabric (2100 routing muxes, thousands of combinational loops
# by construction) makes timing-driven synthesis very slow. build.cfg
# synth_directive (e.g. RuntimeOptimized) trades QoR the multicycle-constrained
# fabric does not need for run time. Not in the fingerprint: it does not change
# the design, so changing it alone does not force a rebuild.
if {[dict exists $cfg synth_directive] && [dict get $cfg synth_directive] ne ""} {
    set_property STEPS.SYNTH_DESIGN.ARGS.DIRECTIVE [dict get $cfg synth_directive] [get_runs synth_1]
    puts "synth_1 directive: [dict get $cfg synth_directive]"
}

# M16: phys_opt_design stays ENABLED, and the property is set explicitly on every run
# because Vivado stores it in the project - a previous run that turned it off keeps it
# off until something turns it back on.
#
# The history is worth keeping: with the old 256-cycle multicycle it was pure cost
# (WNS -465 ns going in, 1 h 15 min of "Critical Path Optimization", 128 ns recovered -
# it cannot fix a fabric path longer than the gce gap). It was disabled for that reason,
# and then route_design died inside "Phase 2.3 Update Timing" with no message. The one
# implementation that ever got past that phase on this fabric had phys_opt in the flow,
# so the netlist the router sees is a suspect and this step goes back in. With the gap
# now covering the fabric (WNS +0.531 ns after placement) it has nothing to fix and
# costs seconds, not an hour - M15 closed at +0.585 ns with it skipping.
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]

# M13: synthesis crashed Vivado (and later restarted the Windows machine) three
# times, each time at the same step: "Applying XDC Timing Constraints", then
# breaking the fabric's combinational routing loops against those clocks, before
# Technology Mapping. Synthesis needs no clocks here: the fabric is multicycle by
# construction and the directive is RuntimeOptimized anyway. So the XDC is used by
# implementation only (pins, IOSTANDARDs and every timing constraint are applied
# there, and timing.rpt still has to close).
set xdc_objs [get_files -quiet -of_objects [get_filesets constrs_1]]
if {[llength $xdc_objs]} {
    set_property USED_IN_SYNTHESIS  false $xdc_objs
    set_property USED_IN_IMPLEMENTATION true $xdc_objs
}

# --- simulation ---------------------------------------------------------------

if {$action eq "sim"} {
    launch_simulation -simset sim_1 -mode behavioral
    run all
    close_sim
    close_project
    return
}

# --- build ----------------------------------------------------------------------

set old ""
if {[file exists $stampf]} {
    set fh [open $stampf r]; set old [string trim [read $fh]]; close $fh
}

proc bob_run_done {run} {
    expr {[get_property PROGRESS [get_runs $run]] eq "100%"}
}

set have_bit [expr {[bob_run_done impl_1] &&
                    [llength [glob -nocomplain [get_property DIRECTORY [get_runs impl_1]]/*.bit]] > 0}]

if {$action ne "force" && $fp eq $old && $have_bit} {
    puts ""
    puts "inputs unchanged since the last build (fingerprint $fp) - skipping"
    puts "synthesis and implementation. Use -tclargs force to rebuild anyway."
} else {
    if {$action eq "force"} {
        puts "forced rebuild"
    } elseif {$old eq ""} {
        puts "first build"
    } else {
        puts "inputs changed ($old -> $fp) - rebuilding"
    }
    catch { reset_run impl_1 }
    catch { reset_run synth_1 }

    puts ""
    puts "starting synthesis and implementation ..."
    puts ""
    launch_runs impl_1 -to_step write_bitstream -jobs $jobs
    wait_on_run impl_1

    # launch_runs does NOT raise on failure, so check explicitly. Without this a
    # broken build exits 0 and leaves a stale bitstream sitting in place.
    foreach run {synth_1 impl_1} {
        if {![bob_run_done $run]} {
            error "run $run did not complete: [get_property PROGRESS [get_runs $run]] / [get_property STATUS [get_runs $run]]"
        }
    }
    set fh [open $stampf w]; puts $fh $fp; close $fh
}

set bit [lindex [glob -nocomplain [get_property DIRECTORY [get_runs impl_1]]/*.bit] 0]
if {$bit eq ""} {
    error "implementation reported success but produced no bitstream"
}

# --- outputs ----------------------------------------------------------------------

file mkdir $out_dir
file copy -force $bit $bitfile

open_run impl_1
report_timing_summary -file $out_dir/timing.rpt
report_utilization    -file $out_dir/util.rpt
report_drc            -file $out_dir/drc.rpt
# The sysclk registers the XDC holds to one cycle by name (u_clk, u_bram_jtag);
# the fabric is flattened, so check none of them was renamed out of the filter.
set fh [open $out_dir/sysclk_1cycle.txt w]
foreach c [lsort [get_cells -quiet -hier -filter {IS_SEQUENTIAL && (NAME =~ *u_bram_jtag/* || NAME =~ *u_clk/*)}]] { puts $fh $c }
close $fh
foreach run {synth_1 impl_1} {
    set log [get_property DIRECTORY [get_runs $run]]/runme.log
    if {[file exists $log]} { file copy -force $log $out_dir/$run.log }
}

# Worst negative slack. Both sources can come back EMPTY, and an empty value
# must not be compared as a number (Tcl falls back to string comparison).
set wns ""
catch { set wns [get_property STATS.WNS [get_runs impl_1]] }
if {![string is double -strict $wns]} {
    catch { set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]] }
}

set fh [open $out_dir/build_info.txt w]
puts $fh "tag         $tag"
puts $fh "top         $top"
puts $fh "idcode      $idcode_txt"
puts $fh "usercode    $usercode_txt"
puts $fh "part        $part"
puts $fh "fingerprint $fp"
puts $fh "wns         [expr {[string is double -strict $wns] ? "$wns ns" : "not reported"}]"
puts $fh "built       [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh "sources"
foreach f $src_files { puts $fh "  [string range $f [expr {[string length $hw_dir] + 1}] end]" }
close $fh

# M20: the fabric's per-element delays on this implementation, for per-design clocks.
# `delays = 0` in build.cfg skips it (it reads timing only; it never changes the design).
# M25: last, after every other report is written, and inside catch: an error here must not
# cost the build its reports (M23/M24 lost build_info.txt this way).
if {![dict exists $cfg delays] || [dict get $cfg delays] ne "0"} {
    if {[catch { source [file join $script_dir extract_delays.tcl] } msg]} {
        puts "extract_delays: FAILED ($msg) - the build and its other reports are fine"
    }
}

puts ""
puts "bitstream : $bitfile"
if {![string is double -strict $wns]} {
    puts "WNS       : not reported"
    puts ""
    puts "On the fabric that is expected: its combinational loops are broken"
    puts "arbitrarily for analysis, so there may be no complete worst path."
    puts "The bitstream is written and usable; see timing.rpt."
} elseif {$wns < 0} {
    puts "WNS       : $wns ns"
    puts ""
    puts "WARNING: timing is not met. The bitstream is still written, because on"
    puts "this design static timing is inconclusive by construction. The usual"
    puts "cause is TCK constrained faster than the fabric settles: raise"
    puts "tck_period in constr/pynq_z2.xdc (the link runs at 100 kHz - 1 MHz)."
} else {
    puts "WNS       : $wns ns"
}
puts "reports   : $out_dir"
puts ""
puts "build OK  - copy $out_dir back to bob_full_v1/docs/reports/$tag/"

# In the GUI leave the project and the implemented design open to look at;
# in batch mode close it so the session ends clean.
if {!$in_gui} { close_project }

if {$action eq "all"} {
    puts ""
    program_board $bitfile
}
