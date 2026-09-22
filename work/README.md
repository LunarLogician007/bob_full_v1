# work/

Your own designs live here; `work/examples/` ships with the project.

bob studio's **Sources → New design** creates `work/<name>/<name>.v` from a template,
and **Pin Planner → write .pcf** puts a pin file beside it. From the command line:

```sh
./bob build work/mything/mything.v
./bob build work/mything/mything.v --pcf work/mything/mything.pcf
./bob load  build/bit/mything.bit --probe usb
```

A design keeps to one clock, no asynchronous resets and no latches: the fabric has one
user clock and every flip-flop is enabled by it. Without a `.pcf` the ports must be
`clk`, `sw[1:0]`, `btn[3:0]`, `led[2:0]`; with one, any ports you like.

## Projects (M18)

A bob studio project can live anywhere on disk: **New Project** makes
`<location>/<name>/<name>.bobproj` with `src/ bd/ ip/ constrs/ build/`. The
block-design example `work/examples/bd_demo/` is one. See the README's *Projects and
block designs*. From the command line: `./bob build --project path/to/x.bobproj`.

## Pin files

A `.pcf` names **one bit per line**, and every port bit is `port[i]` — including a port
that is only one bit wide. `en` is the net `en[0]`, never `en`; a bare name is ignored
and the build then stops with `input en[0] has no pin (pcf set_io)`. The Pin Planner
writes them correctly and refuses a bare name.

```
set_io a[0] SW0
set_io a[1] SW1
set_io a[2] BTN0
set_io en[0] BTN1
set_io y[0] LD0
set_io y[1] LD1
set_io z[0] LD2
```

A pin is a board name (`SW0 SW1 BTN0..BTN3 LD0..LD2`) or `pad<N>` for any of the 44 pads;
pads without a board name are reachable by boundary scan only. `clk` takes no pin.
