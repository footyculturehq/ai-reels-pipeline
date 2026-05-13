import React from 'react';
import { interpolate } from 'remotion';
import { COLORS, FONT } from '../../lib/constants';

interface Feature {
  icon: string;
  label: string;
}

interface FeatureGridParams {
  title?: string;
  features: Feature[];
}

export const FeatureGridTemplate: React.FC<{
  params: Record<string, unknown>;
  frame: number;
  durationFrames: number;
}> = ({ params, frame, durationFrames }) => {
  const { title, features } = params as FeatureGridParams;
  const items = features ?? [];

  const opacity = interpolate(frame, [0, 8, durationFrames - 8, durationFrames], [0, 1, 1, 0], {
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
        padding: '32px 32px',
        background: 'rgba(0,0,0,0.7)',
        opacity,
      }}
    >
      {title && (
        <div
          style={{
            color: COLORS.white,
            fontFamily: FONT.family,
            ...FONT.headline,
            textAlign: 'center',
            marginBottom: 32,
          }}
        >
          {title}
        </div>
      )}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 16,
          width: '100%',
        }}
      >
        {items.map((feature, i) => {
          const delay = i * 6;
          const itemOpacity = interpolate(frame, [delay, delay + 8], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const scale = interpolate(frame, [delay, delay + 8], [0.8, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });

          return (
            <div
              key={i}
              style={{
                background: 'rgba(108, 99, 255, 0.15)',
                border: '1px solid rgba(108, 99, 255, 0.3)',
                borderRadius: 16,
                padding: '20px 16px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 8,
                opacity: itemOpacity,
                transform: `scale(${scale})`,
              }}
            >
              <div style={{ fontSize: 36 }}>{feature.icon}</div>
              <div
                style={{
                  color: COLORS.white,
                  fontFamily: FONT.family,
                  fontSize: 28,
                  fontWeight: 700,
                  textAlign: 'center',
                  lineHeight: 1.2,
                }}
              >
                {feature.label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
