import React from 'react';
import { interpolate } from 'remotion';
import { COLORS, FONT } from '../../lib/constants';

interface BigNumberParams {
  number: string;
  label: string;
  subtext?: string;
  color?: string;
}

export const BigNumberTemplate: React.FC<{
  params: Record<string, unknown>;
  frame: number;
  durationFrames: number;
}> = ({ params, frame, durationFrames }) => {
  const { number, label, subtext, color } = params as BigNumberParams;
  const accentColor = color ?? COLORS.accent;

  const opacity = interpolate(frame, [0, 8, durationFrames - 8, durationFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const scale = interpolate(frame, [0, 15], [0.5, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0,0,0,0.75)',
        opacity,
      }}
    >
      <div
        style={{
          transform: `scale(${scale})`,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}
      >
        <div
          style={{
            color: accentColor,
            fontFamily: FONT.family,
            fontSize: 140,
            fontWeight: 900,
            letterSpacing: '-0.04em',
            lineHeight: 1,
            textShadow: `0 0 40px ${accentColor}66`,
          }}
        >
          {number}
        </div>
        <div
          style={{
            color: COLORS.white,
            fontFamily: FONT.family,
            fontSize: 44,
            fontWeight: 700,
            letterSpacing: '-0.01em',
            textAlign: 'center',
            marginTop: 8,
          }}
        >
          {label}
        </div>
        {subtext && (
          <div
            style={{
              color: 'rgba(255,255,255,0.6)',
              fontFamily: FONT.family,
              fontSize: 28,
              fontWeight: 500,
              textAlign: 'center',
              marginTop: 12,
            }}
          >
            {subtext}
          </div>
        )}
      </div>
    </div>
  );
};
