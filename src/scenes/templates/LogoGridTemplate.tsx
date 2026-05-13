import React from 'react';
import { interpolate, staticFile, Img } from 'remotion';
import { COLORS, FONT } from '../../lib/constants';

interface LogoGridParams {
  title?: string;
  logos: string[];
}

export const LogoGridTemplate: React.FC<{
  params: Record<string, unknown>;
  frame: number;
  durationFrames: number;
}> = ({ params, frame, durationFrames }) => {
  const { title, logos } = params as LogoGridParams;
  const items = logos ?? [];

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
        padding: '32px',
        background: 'rgba(0,0,0,0.75)',
        opacity,
      }}
    >
      {title && (
        <div
          style={{
            color: COLORS.white,
            fontFamily: FONT.family,
            ...FONT.body,
            textAlign: 'center',
            marginBottom: 32,
            opacity: 0.8,
          }}
        >
          {title}
        </div>
      )}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 20,
          justifyContent: 'center',
          alignItems: 'center',
        }}
      >
        {items.map((logo, i) => {
          const delay = i * 4;
          const itemOpacity = interpolate(frame, [delay, delay + 8], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const scale = interpolate(frame, [delay, delay + 10], [0.7, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });

          return (
            <div
              key={i}
              style={{
                width: 100,
                height: 100,
                background: 'rgba(255,255,255,0.08)',
                borderRadius: 20,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                opacity: itemOpacity,
                transform: `scale(${scale})`,
                overflow: 'hidden',
                padding: 12,
              }}
            >
              <Img
                src={staticFile(`logos/${logo}`)}
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
};
