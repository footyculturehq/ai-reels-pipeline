import React from 'react';
import { interpolate } from 'remotion';
import { COLORS, FONT } from '../../lib/constants';

interface BulletsParams {
  title?: string;
  bullets: string[];
}

export const BulletsTemplate: React.FC<{
  params: Record<string, unknown>;
  frame: number;
  durationFrames: number;
}> = ({ params, frame, durationFrames }) => {
  const { title, bullets } = params as BulletsParams;
  const items = bullets ?? [];

  const containerOpacity = interpolate(frame, [0, 8, durationFrames - 8, durationFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const framesPerItem = durationFrames / (items.length + 1);

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '40px 48px',
        background: 'rgba(0,0,0,0.65)',
        opacity: containerOpacity,
      }}
    >
      {title && (
        <div
          style={{
            color: COLORS.accent,
            fontFamily: FONT.family,
            ...FONT.label,
            textTransform: 'uppercase',
            marginBottom: 24,
          }}
        >
          {title}
        </div>
      )}
      {items.map((bullet, i) => {
        const itemDelay = (i + 1) * framesPerItem * 0.4;
        const itemOpacity = interpolate(frame, [itemDelay, itemDelay + 8], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        const itemX = interpolate(frame, [itemDelay, itemDelay + 10], [-30, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });

        return (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              marginBottom: 20,
              opacity: itemOpacity,
              transform: `translateX(${itemX}px)`,
            }}
          >
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: COLORS.accent,
                marginRight: 20,
                marginTop: 8,
                flexShrink: 0,
              }}
            />
            <div
              style={{
                color: COLORS.white,
                fontFamily: FONT.family,
                ...FONT.body,
                textShadow: '0 1px 4px rgba(0,0,0,0.5)',
              }}
            >
              {bullet}
            </div>
          </div>
        );
      })}
    </div>
  );
};
