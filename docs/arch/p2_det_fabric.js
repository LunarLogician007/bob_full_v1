  /* ============================ DRILL-DOWN CONTENT (bob) ============================ */
  /* item = [name, caption, drillId|null, kindKey|null]  ·  row = {t:"flow"|"row", label, items}
     bob pages add: src [[source, what was taken]], why [..], files [[file, role]], tb [[testbench, what]] */
  const F = (label, ...items) => ({ t: "flow", label, items });
  const B = (label, ...items) => ({ t: "row", label, items });
  const DET = {};
  const D = (id, o) => DET[id] = o;
  const TB = "hw/tb/tb_bob.v";

  D("clb", {
    title: "CLB — one BLE per tile", sub: "LUT6 (O6/O5) · carry MUXCY/XORCY · FDRE/FDSE · 71 config bits", k: "CLB", stage: "hw/src/clb/clb.sv",
    rows: [
      F("how a signal reaches the logic",
        ["CHANX / CHANY", "L4 unidirectional · W=24", "routing", "GTX"],
        ["IPIN MUX", "fan-in 4 · 3 bits · 0=const0 1=const1", "cbox", "GTX"],
        ["I[5:0] · CE · SR", "8 routed pins", null, "CLB"]),
      B("inside the BLE",
        ["LUTK", "K=6 · INIT 64 bits · O5 tap", "lut", "CLB"],
        ["CARRY", "MUXCY + XORCY · cin from below", "carry", "DSP"],
        ["FLIP-FLOP", "FDRE/FDSE · CE/SR routed · GSR/GWE/gce", "ff", "CLB"]),
      F("and back out",
        ["O · O5", "OPINs · fc_out 0.10", null, "CLB"],
        ["CHANNEL MUXES", "the wires starting here", "sbox", "GTX"]),
      B("dedicated", ["COUT → CIN", "VPR direct, CLB above, no bits", "carry", "DSP"])],
    notes: ["16 CLBs at x ∈ {1,2,4,5}, y 1…4 (board profile; the frozen 8×8 profile has 48). Each is <b>one BLE</b>: VPR's k6_frac_N10 packs 10 BLEs + local interconnect per cluster, which would cost far more configuration flip-flops than an XC7Z020 can hold as shift + shadow register pairs.",
      "The CLB word is <b>71 bits</b>: INIT[63:0], ff_en, ff_rstval, ff_ce_en, ff_sr_en, cy_en, cy_di_sel, ff_d_sel. The routing bits of the same tile sit right after it in the chain.",
      "Flip-flops run on <b>sysclk</b> with <code>gce</code> as the user clock — an enable, never a derived clock (UG949).",
      "M8 synthesis maps onto exactly this: <code>$lut</code>, <code>BOB_FDRE/FDSE</code>, <code>BOB_ADD</code> (LUT A^B + carry)."],
    src: [["AMD UG474 (7-series CLB)", "LUT6_2 fracture (O5 = INIT[31:0] over i[4:0]), CARRY4 MUXCY/XORCY, FDRE/FDSE priority (SR beats CE)"],
      ["OpenFPGA k6_frac_N10_tileable…dsp36 (VPR arch)", "tile pin interface I/O/cin/cout, fc_in 0.15 / fc_out 0.10, carry as a direct"],
      ["bob/rtl/clb.sv (hardware-proven)", "the original CLB, reused and extended with CE/SR, GSR/GWE, K"]],
    why: ["UG474 is the silicon bob is emulated on: matching its LUT6_2 and FDRE semantics means yosys' xilinx-proven mapping ideas apply directly.",
      "OpenFPGA's arch is regression-tested with VPR, so the pin/fc choices route in practice; bob only reduced N10 to N1."],
    files: [["hw/src/clb/clb.sv", "the BLE"], ["hw/src/clb/lutk.sv", "K-input fracturable LUT"], ["hw/src/clb/clb_pkg.sv", "field offsets, INIT helpers"],
      ["hw/src/generated/bob_fabric.v", "16 instances u_clb_x*y*"], ["tools/bob/device.py", "clb fields, pins, VPR tile"],
      ["tools/bob/model.py", "clb_comb / clb_next"], ["host/bitstream.py", "Design.lut()"], ["tools/bob/place.py", "M8 packer"]],
    tb: [["hw/tb/tb_clb.sv", "7040 checks — every flag combination vs model.py"], [TB + " [9][10][21][22]", "routed CE/SR, carry counters, random netlists every clock"],
      ["hw/tb/tb_synth.v", "yosys designs on the fabric vs source Verilog"], ["tests/test_lutk.py", "lutk(6) == original lut6"]],
    drill: ["lut", "carry", "ff", "cbox", "sbox"]
  });

  D("lut", {
    title: "LUT6 — lutk.sv", sub: "a 64:1 mux tree over INIT · O5 tap at the 32-bit boundary", k: "CLB", stage: "hw/src/clb/lutk.sv",
    rows: [F("the mux tree", ["INIT[63:0]", "64 chain bits", "chain", "CFG"], ["2:1 × 63", "six stages", null, "CLB"], ["O6", "any 6-input function", null, "CLB"]),
      B("fracturable tap", ["O5", "INIT[i[4:0]] — any 5-input function", null, "CLB"])],
    notes: ["Parameter <b>K</b> (device.py lut_k): the same RTL runs at K=4 — <code>sim/run_k4_sim.sh</code> proves it on the whole FPGA.",
      "O5 lets the M8 packer keep a LUT's extra loads when its flip-flop takes O6."],
    src: [["AMD UG474 LUT6_2", "O6/O5 fracture definition"], ["bob/rtl/lut6.sv", "hardware-proven original (docs/reference/lut6.sv)"]],
    why: ["Keeping the proven lut6 as the golden reference lets pytest prove the parameterised version equal at K=6."],
    files: [["hw/src/clb/lutk.sv", "RTL"], ["tools/bob/model.py", "clb_comb"], ["tools/bob/synth.py", "abc -lut K"]],
    tb: [["tests/test_lutk.py", "lutk(6) == lut6 on 3000 vectors; K=4 vs Python"], ["hw/tb/tb_clb.sv", "flag sweep"]],
    drill: ["clb", "chain"]
  });

  D("carry", {
    title: "Carry chain — MUXCY / XORCY", sub: "cout of CLB (x,y) is cin of CLB (x,y+1) · 42 VPR directs", k: "DSP", stage: "hw/src/clb/clb.sv",
    rows: [F("one bit (cy_en = 1)", ["CIN", "from below / row 1: USER1 cin", null, "DSP"], ["S = O6", "propagate", null, "CLB"],
        ["MUXCY", "CO = S ? CIN : DI", null, "DSP"], ["XORCY", "sum = S ^ CIN → FF D / O", null, "DSP"]),
      B("generate input", ["DI", "cy_di_sel: 0 = I0, 1 = O5", null, "CLB"])],
    notes: ["Directs cost <b>no configuration bits</b>: in the rr graph an IPIN driven only by an OPIN is a wire.",
      "M8 puts a <b>generator CLB</b> at row 1 (LUT 0, DI = I0 = carry in) so the JTAG USER1 cin never enters a synthesised design, and a <b>tap CLB</b> (sum = carry) when a chain continues in another column.",
      "An 8-bit counter up column 8 is checked for 300 consecutive clocks in simulation and on the board."],
    src: [["AMD UG474 CARRY4", "MUXCY/XORCY equations, DI/S naming"], ["OpenFPGA arch directlist adder_carry", "carry as a VPR direct (bob runs it South→North)"],
      ["yosys share/xilinx/arith_map.v", "$alu → per-bit carry cells (M8 BOB_ADD)"]],
    why: ["The direct keeps arithmetic off the general routing — the same reason CARRY4 exists.", "arith_map.v is yosys' tested mapping; bob only adds the DI = I0 constraint."],
    files: [["hw/src/clb/clb.sv", "carry logic"], ["hw/src/generated/bob_fabric.v", "assign rCIN = rCOUT (directs)"], ["tools/bob/synth/bob_map.v", "_80_bob_alu"], ["tools/bob/place.py", "chains, generators, taps"]],
    tb: [[TB + " [10][11][21]", "4-bit and 8-bit counters vs model"], ["hwtest counter-step / counter8 / synth-blinky", "on the board"]],
    drill: ["clb", "ff"]
  });

  D("ff", {
    title: "Flip-flop — FDRE / FDSE", sub: "sysclk + gce · SR beats CE · INIT = rstval = GSR value", k: "CLB", stage: "hw/src/clb/clb.sv",
    rows: [F("priority, highest first", ["GSR", "q ← ff_rstval", "startup", "CFG"], ["GWE · gce", "else hold", "clock", "CMT"],
        ["SR (ff_sr_en)", "q ← ff_rstval", null, "CLB"], ["CE (ff_ce_en)", "q ← D", null, "CLB"]),
      B("D source", ["O6", "ff_d_sel 0", null, "CLB"], ["O5", "ff_d_sel 1", null, "CLB"], ["sum", "when cy_en", "carry", "DSP"])],
    notes: ["The M3 hardware <code>gsr-gwe</code> check steps JSTART one TCK at a time and proves the FF is frozen with GSR=0, GWE=0.",
      "CE and SR are <b>routed pins</b> (UG474 per-slice CE/SR), so M8 synthesis puts enables and sync resets straight on them."],
    src: [["AMD UG474 FDRE/FDSE", "SR over CE, INIT"], ["AMD UG470 startup", "GSR / GWE meaning"], ["AMD UG949", "clock enables instead of derived clocks"]],
    why: ["Matching FDRE/FDSE lets yosys dfflegalize target $_SDFFE_PP0P_/PP1P_ with init = reset."],
    files: [["hw/src/clb/clb.sv", "q_reg"], ["hw/src/core/clock_ctrl.v", "gce, synchronised GSR/GWE"], ["tools/bob/synth/bob_map.v", "FF techmap"]],
    tb: [["hw/tb/tb_clb.sv", "GSR/GWE/gce/CE/SR sweep"], [TB + " [7][9]", "startup edges, routed CE/SR incl. INTEST autostep"]],
    drill: ["clb", "startup", "clock"]
  });

  D("routing", {
    title: "Routing — VPR's rr graph as hardware", sub: "W=24 · L4 unidirectional · Wilton Fs=3 · 2105 muxes · 5934 bits", k: "GTX", stage: "tools/bob/fabric_gen.py",
    rows: [F("the flow that builds it",
        ["device.py ARCH", "grid, pins, W, fc", null, "HARD"], ["vpr_arch.py", "bob_k6.xml", null, "HARD"],
        ["VPR (Docker)", "routes and2.blif, writes rr_graph", null, "HARD"], ["device.py", "nodes with drivers → muxes → chain", "chain", "CFG"],
        ["fabric_gen.py", "bob_fabric.v", null, "HARD"]),
      B("mux kinds", ["CHANX 719", "wire starts: 0=const0, 1+i", "sbox", "GTX"], ["CHANY 594", "same encoding", "sbox", "GTX"],
        ["IPIN 792", "0=const0 1=const1 2+i", "cbox", "GTX"]),
      B("free", ["90 directs", "carry + DSP cascade", "carry", "DSP"], ["125 undriven", "bottom cin, clk, dsp0 pcin, 19 edge wires", null, "GTX"])],
    notes: ["<b>RTL, router, model and VPR use one graph.</b> The rr graph is committed (<code>tools/bob/arch/bob_k6_rr.xml.gz</code>) with the sha256 of the arch that made it; <code>make check</code> fails if they drift.",
      "An all-zero chain selects const0 everywhere, so a dark fabric has <b>no loops</b>; the netlist still has thousands of potential cycles — Vivado LUTLP-1 is waived for bob_top.",
      "W=24 was measured: 8×8 with W=16 → 4.2k routing bits, W=24 → 6.0k, W=32 → 7.8k."],
    src: [["OpenFPGA k6_frac_N10_tileable_adder_chain_dpram8K_dsp36_fracff_40nm.xml", "tileable layout, L4 unidir segment, Wilton Fs=3, fc, switches"],
      ["OpenFPGA fabric generation method", "every rr node with fan-in becomes a routing multiplexer"], ["VPR 9 (OpenFPGA Docker)", "builds the tileable rr graph"]],
    why: ["A router and a fabric generated from different descriptions produce bitstreams that route in software and fail in hardware; VPR's graph is the single source.",
      "The reference arch is regression-tested, so the channel structure is known to route real benchmarks (M9 will run VPR on bob's own designs)."],
    files: [["tools/bob/vpr_arch.py", "arch XML"], ["tools/bob/vpr_rrgraph.sh", "VPR run"], ["tools/bob/rrgraph.py", "graph reader"], ["tools/bob/device.py", "muxes + chain"],
      ["tools/bob/fabric_gen.py", "RTL"], ["hw/src/fabric/bob_mux.v", "one mux"], ["host/bitstream.py", "BFS router over the graph"], ["tools/bob/model.py", "evaluates the same muxes"]],
    tb: [[TB + " [3][22]", "routed designs + 4 random routed netlists, every CLB output every clock"], ["tests/test_device.py", "encoding, pips unique, pins, directs, trees never share wires"],
      ["sim/mutate_fabric.sh", "mux-no-const1, mux-inputs-shifted, carry-direct-cut killed"]],
    drill: ["sbox", "cbox", "chain", "clb"]
  });

  D("sbox", {
    title: "Switch box — wire-start muxes", sub: "CHANX/CHANY node · fan-in 1…12 · bits = ⌈log2(N+1)⌉", k: "GTX", stage: "hw/src/fabric/bob_mux.v",
    rows: [F("one L4 wire", ["SELECT", "chain bits at the wire's start tile", "chain", "CFG"], ["bob_mux", "0 const0 · 1+i input i", null, "GTX"], ["WIRE (4 tiles)", "one rr node, ptc per position", null, "GTX"]),
      B("inputs (ascending rr node id)", ["ending / passing wires", "Wilton Fs=3", null, "GTX"], ["OPINs", "CLB O/O5, BRAM DO, DSP P, pad in", null, "CLB"])],
    notes: ["A mux lives at <b>(xlow,ylow)</b> for an INC_DIR wire and <b>(xhigh,yhigh)</b> for DEC_DIR — where the wire is driven.",
      "Wider fan-ins (11–12) appear where many wires meet; single-input muxes still cost one bit so 0 stays const0."],
    src: [["OpenFPGA / VPR tileable rr graph", "the edges into each wire"], ["bob mux convention (M1)", "value 0 = const0 so all-zero is inert"]],
    why: ["Keeping 0 = const0 from the first 4×4 fabric keeps random/partial chains loop-free in simulation (the M4 hang)."],
    files: [["hw/src/fabric/bob_mux.v", "tab[sel]"], ["hw/src/generated/bob_fabric.v", "m<id> instances"]],
    tb: [["tests/test_device.py::test_mux_encoding", "minimal width, inputs == VPR fan-in"], ["sim/mutate_fabric.sh", "mux-inputs-shifted killed"]],
    drill: ["routing", "cbox"]
  });

  D("cbox", {
    title: "Connection box — IPIN muxes", sub: "fc_in 0.15 × W=24 → fan-in 4 · 0=const0 · 1=const1", k: "GTX", stage: "hw/src/fabric/bob_mux.v",
    rows: [F("one block pin", ["4 channel wires", "fc_in", "sbox", "GTX"], ["bob_mux C1=1", "3 bits", null, "GTX"], ["IPIN", "LUT I, CE, SR, BRAM/DSP pin, pad out", null, "CLB"])],
    notes: ["const1 on IPINs lets designs tie CE/EN/B-bits high <b>without routing</b> (the pipeline's B = 3 uses it).", "680 IPINs have fan-in 4, 112 have fan-in 2."],
    src: [["OpenFPGA arch fc_in 0.15", "tracks per pin"], ["bob (M7)", "const1 option on IPINs"]],
    why: ["Constants are common on hard-block pins; generating them in LUTs would waste CLBs out of 16."],
    files: [["hw/src/fabric/bob_mux.v", "C1 parameter"], ["host/bitstream.py", "Design._sink / Const"]],
    tb: [["sim/mutate_fabric.sh", "mux-no-const1 killed"], [TB + " [20]", "pipeline uses const1 B pins"]],
    drill: ["routing", "sbox", "clb"]
  });
