import React from 'react';
import { useCurrentFrame } from 'remotion';
import { secToFrame } from '../lib/constants';
import type { SceneConfig } from '../lib/dynamic-config';
import { HookTemplate } from '../scenes/templates/HookTemplate';
import { BulletsTemplate } from '../scenes/templates/BulletsTemplate';
import { FeatureGridTemplate } from '../scenes/templates/FeatureGridTemplate';
import { BigNumberTemplate } from '../scenes/templates/BigNumberTemplate';
import { ContrastTemplate } from '../scenes/templates/ContrastTemplate';
import { StrikethroughTemplate } from '../scenes/templates/StrikethroughTemplate';
import { LogoGridTemplate } from '../scenes/templates/LogoGridTemplate';
import { ClosingTemplate } from '../scenes/templates/ClosingTemplate';

const TEMPLATE_MAP = {
  hook: HookTemplate,
  bullets: BulletsTemplate,
  featureGrid: FeatureGridTemplate,
  bigNumber: BigNumberTemplate,
  contrast: ContrastTemplate,
  strikethrough: StrikethroughTemplate,
  logoGrid: LogoGridTemplate,
  closing: ClosingTemplate,
} as const;

export const DynamicSceneRenderer: React.FC<{ scenes: SceneConfig[] }> = ({ scenes }) => {
  const frame = useCurrentFrame();

  if (!scenes || scenes.length === 0) return null;

  return (
    <>
      {scenes.map((scene, i) => {
        const startFrame = secToFrame(scene.startSec);
        const endFrame = secToFrame(scene.endSec);

        if (frame < startFrame || frame >= endFrame) return null;

        const Template = TEMPLATE_MAP[scene.type];
        if (!Template) return null;

        const localFrame = frame - startFrame;
        const durationFrames = endFrame - startFrame;

        return (
          <div
            key={`scene-${i}`}
            style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}
          >
            <Template
              params={scene.params}
              frame={localFrame}
              durationFrames={durationFrames}
            />
          </div>
        );
      })}
    </>
  );
};
