import React from "react";
import { View } from "react-native";
import Svg, { Path } from "react-native-svg";

type Props = {
  data: number[];
  color: string;
  width?: number;
  height?: number;
  strokeWidth?: number;
};

/**
 * Tiny non-interactive line sparkline used in dashboard cards.
 */
export default function Sparkline({ data, color, width = 80, height = 28, strokeWidth = 1.5 }: Props) {
  if (!data || data.length < 2) {
    return <View style={{ width, height }} />;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  const pts = data.map((v, i) => {
    const x = i * step;
    const y = height - ((v - min) / range) * height;
    return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  });
  return (
    <Svg width={width} height={height}>
      <Path d={pts.join(" ")} stroke={color} strokeWidth={strokeWidth} fill="none" />
    </Svg>
  );
}
