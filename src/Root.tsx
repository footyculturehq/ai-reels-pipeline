import {registerRoot} from 'remotion';
import React from 'react';
import { Composition } from 'remotion';
import { DynamicReel } from './DynamicReel';
import { FPS, WIDTH, HEIGHT } from './lib/constants';
import type { ReelConfig } from './lib/dynamic-config';

const defaultConfig: ReelConfig = {
  id: 'preview',
  duration: 750,
  avatarSrc: 'avatars/avatar-preview.mp4',
  avatarMarginTop: -280,
  brollSegments: [],
  captionChunks: [],
  scenes: [],
};

export const Root: React.FC = () => (
  <Composition
    id="DynamicReel"
    component={DynamicReel}
    durationInFrames={750}
    width={WIDTH}
    height={HEIGHT}
    fps={FPS}
    defaultProps={{ config: defaultConfig }}
    calculateMetadata={({ props }) => ({
      durationInFrames: props.config?.duration ?? 750,
    })}
  />
);

registerRoot(Root);
