# traffic.sdc - the fabric clock this design must meet (M20)
# 32 Hz. The build fails if the design's timing misses it.
create_clock -period 31250000.000 -name clk [get_ports clk]
