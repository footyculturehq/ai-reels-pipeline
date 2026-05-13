import React from 'react';
import { interpolate } from 'remotion';
import { COLORS, FONT } from '../../lib/constants';

interface ClosingParams {
  cta: string;
  subtext?: string;
  badge?: string;
}

export const ClosingTemplate: React.FC<{
  params: Record<string, unknown>;
  frame: number;
  durationFrames: number;
}> = ({ params, frame, durationFrames }) => {
  const { cta, subtext, badge } = params as ClosingParams;

  const opacity = interpolate(frame, [0, 10, durationFrames - 8, durationFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const scale = interpolate(frame, [0, 15], [0.85, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const badgeOpacity = interpolate(frame, [durationFrames * 0.3, durationFrames * 0.55], [0, 1], {
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
            background: 'linear-gradient(135deg, #6C63FF, #C030E0)',
            borderRadius: 24,
            padding: '20px 48px',
            marginBottom: 20,
          }}
        >
          <div
            style={{
              color: COLORS.white,
              fontFamily: FONT.family,
              fontSize: 48,
              fontWeight: 900,
              letterSpacing: '-0.02em',
              textAlign: 'center',
            }}
          >
            {cta}
          </div>
        </div>

        {subtext && (
          <div
            style={{
              color: 'rgba(255,255,255,0.7)',
              fontFamily: FONT.family,
              fontSize: 30,
              fontWeight: 500,
              textAlign: 'center',
              marginBottom: badge ? 20 : 0,
            }}
          >
            {subtext}
          </div>
        )}

        {badge && (
          <div
            style={{
              opacity: badgeOpacity,
              background: COLORS.green,
              borderRadius: 12,
              padding: '8px 24px',
            }}
          >
            <div
              style={{
                color: '#000',
                fontFamily: FONT.family,
                ...FONT.label,
                fontWeight: 800,
              }}
            >
              {badge}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
