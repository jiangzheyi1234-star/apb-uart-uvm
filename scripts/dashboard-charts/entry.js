import { init, use, version } from "echarts/core";
import { HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, VisualMapPiecewiseComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

use([HeatmapChart, GridComponent, TooltipComponent, VisualMapPiecewiseComponent, SVGRenderer]);
window.UARTECharts = { init, version };
