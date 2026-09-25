# -----------------------------------------------------------------------------
# bob_cfg.tcl - read hw/build.cfg (shared by build.tcl and delays.tcl; plain Tcl)
# -----------------------------------------------------------------------------

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
