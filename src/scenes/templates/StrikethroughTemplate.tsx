import React from 'react';
import { interpolate } from 'remotion';
import { COLORS, FONT } from '../../lib/constants';

interface StrikethroughParams {
  oldWay: string;
  newWay: string;
  label?: string;
}

export const StrikethroughTemplate: React.FC<{
  params: Record<string, unknown>;
  frame: number;
  durationFrames: number;
}> = ({ params, frame, durationFrames }) => {
  const { oldWay, newWay, label } = params as StrikethroughParams;

  const opacity = interpolate(frame, [0, 8, durationFrames - 8, durationFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const strikeWidth = interpolate(frame, [durationFrames * 0.2, durationFrames * 0.5], [0, 100], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const newOpacity = interpolate(frame, [durationFrames * 0.45, durationFrames * 0.65], [0, 1], {
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
        padding: '40px',
        background: 'rgba(0,0,0,0.72)',
        opacity,
      }}
    >
      {label && (
        <div
          style={{
            color: COLORS.amber,
            fontFamily: FONT.family,
            ...FONT.label,
            textTransform: 'uppercase',
            marginBottom: 24,
          }}
        >
          {label}
        </div>
      )}

      {/* Old way with animated strikethrough */}
      <div style={{ position: 'relative', marginBottom: 32 }}>
        <div
          style={{
            color: 'rgba(255,255,255,0.6)',
            fontFamily: FONT.family,
            ...FONT.body,
            textAlign: 'center',
          }}
        >
          {oldWay}
        </div>
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: 0,
            height: 3,
            width: `${strikeWidth}%`,
            background: COLORS.red,
            transform: 'translateY(-50%)',
            borderRadius: 2,
          }}
        />
      </div>

      {/* New way */}
      <div
        style={{
          opacity: newOpacity,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <div
          style={{
            color: COLORS.green,
            fontFamily: FONT.family,
            fontSize: 32,
            fontWeight: 900,
          }}
        >
          ✓
        </div>
        <div
          style={{
            color: COLORS.white,
            fontFamily: FONT.family,
            ...FONT.body,
            textAlign: 'center',
          }}
        >
          {newWay}
        </div>
      </div>
    </div>
  );
};
