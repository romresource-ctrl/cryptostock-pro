import React from "react";
import { View } from "react-native";
import Svg, { Line, Path } from "react-native-svg";

import { useTheme } from "@/src/theme/ThemeContext";

type Candle = { t: number; open: number; high: number; low: number; close: number };

type Props = {
  candles: Candle[];
  width: number;
  height: number;
};

/**
 * Lightweight area + line chart for asset detail view.
 * Uses closing prices only — fast & avoids candle-rendering cost on RN.
 */
export default function PriceChart({ candles, width, height }: Props) {
  const { colors } = useTheme();
  if (!candles || candles.length < 2) {
    return <View style={{ width, height, backgroundColor: colors.surface }} />;
  }
  const closes = candles.map((c) => c.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const padBottom = 20;
  const usableH = height - padBottom;

  const step = width / (closes.length - 1);
  const points = closes.map((v, i) => ({
    x: i * step,
    y: ((max - v) / range) * usableH,
  }));

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ");
  const areaPath =
    `M 0 ${usableH} ` +
    points.map((p) => `L ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ") +
    ` L ${width} ${usableH} Z`;

  const trendUp = closes[closes.length - 1] >= closes[0];
  const lineColor = trendUp ? colors.accentUp : colors.accentDown;

  // 4 horizontal grid lines
  const grids = [0.25, 0.5, 0.75].map((p) => p * usableH);

  return (
    <Svg width={width} height={height}>
      {grids.map((y, i) => (
        <Line
          key={i}
          x1={0}
          x2={width}
          y1={y}
          y2={y}
          stroke={colors.border}
          strokeWidth={0.5}
          strokeDasharray="3 4"
        />
      ))}
      <Path d={areaPath} fill={lineColor} opacity={0.12} />
      <Path d={linePath} stroke={lineColor} strokeWidth={2} fill="none" />
    </Svg>
  );
}
