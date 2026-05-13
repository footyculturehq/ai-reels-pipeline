import React from 'react';
import { useCurrentFrame, interpolate, Sequence, staticFile, OffthreadVideo, Img } from 'remotion';
import { FPS, TOP_HEIGHT, secToFrame } from '../lib/constants';
import type { BRollSegment } from '../lib/dynamic-config';

export const DynamicBRoll: React.FC<{
  segments: BRollSegment[];
  crossfadeFrames?: number;
}> = ({ segments, crossfadeFrames }) => {
  const frame = useCurrentFrame();
  const CF = crossfadeFrames ?? 8;

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: TOP_HEIGHT,
        overflow: 'hidden',
        backgroundColor: '#080808',
      }}
    >
      {segments.map((seg, i) => {
        const startFrame = secToFrame(seg.startSec);
        const endFrame = secToFrame(seg.endSec);

        if (frame < startFrame - CF || frame > endFrame + CF) return null;

        const fadeIn = interpolate(frame, [startFrame, startFrame + CF], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        const fadeOut = interpolate(frame, [endFrame - CF, endFrame], [1, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        const opacity = Math.min(fadeIn, fadeOut);
        if (opacity <= 0) return null;

        const progress = interpolate(frame, [startFrame, endFrame], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        const scaleFrom = seg.scaleFrom ?? 1.0;
        const scaleTo = seg.scaleTo ?? 1.05;
        const scale = scaleFrom + (scaleTo - scaleFrom) * progress;

        const seqStart = Math.max(0, startFrame - CF);
        const seqDuration = endFrame + CF - seqStart;

        const fit = seg.objectFit ?? 'cover';
        const mediaStyle: React.CSSProperties = {
          width: '100%',
          height: '100%',
          objectFit: fit,
          objectPosition: seg.objectPosition ?? 'center center',
          transform: `scale(${scale})`,
          transformOrigin: 'center center',
          ...(fit === 'contain' ? { padding: '15%' } : {}),
        };

        return (
          <div
            key={`broll-${i}`}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              opacity,
            }}
          >
            {seg.video ? (
              <Sequence from={seqStart} durationInFrames={seqDuration} layout="none">
                <OffthreadVideo
                  src={staticFile(`broll/clips/${seg.video}`)}
                  startFrom={seg.videoStartSec ? Math.round(seg.videoStartSec * FPS) : undefined}
                  style={mediaStyle}
                  muted
                />
              </Sequence>
            ) : seg.image ? (
              <Img src={staticFile(`broll/${seg.image}`)} style={mediaStyle} />
            ) : null}
          </div>
        );
      })}

      {/* Vignette overlay */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          background:
            'radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.3) 100%)',
          pointerEvents: 'none',
        }}
      />
    </div>
  );
};
