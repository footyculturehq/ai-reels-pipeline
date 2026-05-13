import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { FONT, secToFrame } from '../lib/constants';
import type { CaptionChunk } from '../lib/dynamic-config';

export const DynamicCaptionOverlay: React.FC<{
  chunks: CaptionChunk[];
  topOffset: number;
}> = ({ chunks, topOffset }) => {
  const frame = useCurrentFrame();

  let activeChunk: CaptionChunk | null = null;
  for (const chunk of chunks) {
    if (frame >= secToFrame(chunk.startSec) && frame < secToFrame(chunk.endSec)) {
      activeChunk = chunk;
      break;
    }
  }
  if (!activeChunk) return null;

  const startFrame = secToFrame(activeChunk.startSec);
  const endFrame = secToFrame(activeChunk.endSec);

  const scaleIn = interpolate(frame, [startFrame, startFrame + 3], [0.7, 1.0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacityIn = interpolate(frame, [startFrame, startFrame + 2], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacityOut = interpolate(frame, [endFrame - 2, endFrame], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        position: 'absolute',
        top: topOffset - 32,
        left: 0,
        width: '100%',
        display: 'flex',
        justifyContent: 'center',
        zIndex: 100,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          opacity: Math.min(opacityIn, opacityOut),
          transform: `scale(${scaleIn})`,
          background: '#000000',
          borderRadius: 12,
          paddingLeft: 32,
          paddingRight: 32,
          paddingTop: 12,
          paddingBottom: 14,
          boxShadow: '0 4px 24px rgba(0,0,0,0.7), 0 0 0 2px #B0FF00',
        }}
      >
        <div
          style={{
            color: '#B0FF00',
            fontFamily: FONT.family,
            fontSize: 50,
            fontWeight: 800,
            letterSpacing: '-0.01em',
            lineHeight: 1.1,
            textAlign: 'center',
            textShadow: '0 0 20px rgba(176, 255, 0, 0.4)',
            whiteSpace: 'nowrap',
          }}
        >
          {activeChunk.text}
        </div>
      </div>
    </div>
  );
};
