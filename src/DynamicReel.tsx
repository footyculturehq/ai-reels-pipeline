import React from 'react';
import { AbsoluteFill, staticFile } from 'remotion';
import { Video } from '@remotion/media';
import { COLORS, TOP_HEIGHT, BOTTOM_HEIGHT } from './lib/constants';
import type { ReelConfig } from './lib/dynamic-config';
import { DynamicBRoll } from './components/DynamicBRoll';
import { DynamicCaptionOverlay } from './components/DynamicCaptionOverlay';
import { DynamicSceneRenderer } from './components/DynamicSceneRenderer';

export const DynamicReel: React.FC<{ config: ReelConfig }> = ({ config }) => {
  const avatarMarginTop = config.avatarMarginTop ?? -280;
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.darkBg }}>
      {/* TOP HALF: B-roll + scene overlays */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: TOP_HEIGHT,
          overflow: 'hidden',
        }}
      >
        <DynamicBRoll segments={config.brollSegments} crossfadeFrames={config.crossfadeFrames} />
        <DynamicSceneRenderer scenes={config.scenes} />
      </div>

      {/* DIVIDER LINE */}
      <div
        style={{
          position: 'absolute',
          top: TOP_HEIGHT,
          left: 0,
          width: '100%',
          height: 2,
          background: COLORS.divider,
          zIndex: 10,
        }}
      />

      {/* CAPTION PILL at seam */}
      <DynamicCaptionOverlay chunks={config.captionChunks} topOffset={TOP_HEIGHT} />

      {/* BOTTOM HALF: Avatar video */}
      <div
        style={{
          position: 'absolute',
          top: TOP_HEIGHT + 2,
          left: 0,
          width: '100%',
          height: BOTTOM_HEIGHT - 2,
          overflow: 'hidden',
          backgroundColor: '#000000',
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'center',
        }}
      >
        <Video
          src={staticFile(config.avatarSrc)}
          style={{ width: '100%', height: 'auto', marginTop: avatarMarginTop }}
        />
      </div>
    </AbsoluteFill>
  );
};
