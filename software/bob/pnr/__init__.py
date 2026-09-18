"""
pnr - bob's own pack, place and route in Python (M12a), checked against VPR.

  netlist.py   the prepared netlist (vpr_run.prepare: the eblif VPR also gets) -> atoms
  pack.py      atoms -> clusters (one BLE per CLB), carry-chain macros, nets between clusters
  place.py     simulated annealing (VPR's placer: bounding-box cost, adaptive temperature
               and range limit), macros move as a unit, pads fixed
  route.py     PathFinder negotiated congestion with A* on the committed rr graph
  write.py     the result in VPR's own formats (.net .place .route + sidecar), so FASM,
               bitgen, .bit and every check are shared with the VPR flow unchanged
  run.py       software/bob/pnr/run.py <example> [--seed N]; compare.py: Python vs VPR report

The rr graph, pins and chain layout come from software/bob/device.json (software/host/bitstream.py).
"""
