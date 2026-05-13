import React from 'react';
import { interpolate } from 'remotion';
import { COLORS, FONT } from '../../lib/constants';

interface HookParams {
  headline: string;
  subtext?: string;
  accent?: string;
}

export const HookTemplate: React.FC<{
  params: Record<string, unknown>;
  frame: number;
  durationFrames: number;
}> = ({ params, frame, durationFrames }) => {
  const { headline, subtext, accent } = params as HookParams;

  const opacity = interpolate(frame, [0, 8, durationFrames - 8, durationFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const translateY = interpolate(frame, [0, 12], [40, 0], {
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
        padding: '48px 40px',
        background: 'linear-gradient(180deg, rgba(0,0,0,0.0) 0%, rgba(0,0,0,0.7) 100%)',
        opacity,
        transform: `translateY(${translateY}px)`,
      }}
    >
      {accent && (
        <div
          style={{
            color: COLORS.accent,
            fontFamily: FONT.family,
            ...FONT.label,
            textTransform: 'uppercase',
            marginBottom: 12,
          }}
        >
          {accent}
        </div>
      )}
      <div
        style={{
          color: COLORS.white,
          fontFamily: FONT.family,
          ...FONT.headline,
          textAlign: 'center',
          textShadow: '0 2px 12px rgba(0,0,0,0.8)',
        }}
      >
        {headline}
      </div>
      {subtext && (
        <div
          style={{
            color: 'rgba(255,255,255,0.8)',
            fontFamily: FONT.family,
            ...FONT.body,
            textAlign: 'center',
            marginTop: 20,
            textShadow: '0 1px 6px rgba(0,0,0,0.6)',
          }}
        >
          {subtext}
        </div>
      )}
    </div>
  );
};
