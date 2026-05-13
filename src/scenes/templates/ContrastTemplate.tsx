import React from 'react';
import { interpolate } from 'remotion';
import { COLORS, FONT } from '../../lib/constants';

interface ContrastParams {
  before: string;
  after: string;
  beforeLabel?: string;
  afterLabel?: string;
}

export const ContrastTemplate: React.FC<{
  params: Record<string, unknown>;
  frame: number;
  durationFrames: number;
}> = ({ params, frame, durationFrames }) => {
  const { before, after, beforeLabel, afterLabel } = params as ContrastParams;

  const opacity = interpolate(frame, [0, 8, durationFrames - 8, durationFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const afterOpacity = interpolate(frame, [durationFrames * 0.4, durationFrames * 0.6], [0, 1], {
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
        background: 'rgba(0,0,0,0.72)',
        opacity,
        overflow: 'hidden',
      }}
    >
      {/* BEFORE (top half) */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
          padding: '24px 40px',
        }}
      >
        <div
          style={{
            color: COLORS.red,
            fontFamily: FONT.family,
            ...FONT.label,
            textTransform: 'uppercase',
            marginBottom: 8,
          }}
        >
          {beforeLabel ?? 'Before'}
        </div>
        <div
          style={{
            color: 'rgba(255,255,255,0.7)',
            fontFamily: FONT.family,
            ...FONT.body,
            textAlign: 'center',
          }}
        >
          {before}
        </div>
      </div>

      {/* AFTER (bottom half) */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24px 40px',
          opacity: afterOpacity,
        }}
      >
        <div
          style={{
            color: COLORS.green,
            fontFamily: FONT.family,
            ...FONT.label,
            textTransform: 'uppercase',
            marginBottom: 8,
          }}
        >
          {afterLabel ?? 'After'}
        </div>
        <div
          style={{
            color: COLORS.white,
            fontFamily: FONT.family,
            ...FONT.body,
            textAlign: 'center',
          }}
        >
          {after}
        </div>
      </div>
    </div>
  );
};
