export interface BRollSegment {
  video?: string;
  image?: string;
  startSec: number;
  endSec: number;
  objectPosition?: string;
  scaleFrom?: number;
  scaleTo?: number;
  videoStartSec?: number;
  objectFit?: 'cover' | 'contain';
  _speech?: string;
}

export interface CaptionChunk {
  text: string;
  startSec: number;
  endSec: number;
}

export type SceneType =
  | 'hook'
  | 'bullets'
  | 'featureGrid'
  | 'bigNumber'
  | 'contrast'
  | 'strikethrough'
  | 'logoGrid'
  | 'closing';

export interface SceneConfig {
  type: SceneType;
  startSec: number;
  endSec: number;
  params: Record<string, unknown>;
}

export interface ReelConfig {
  id: string;
  duration: number;
  avatarSrc: string;
  avatarMarginTop?: number;
  brollSegments: BRollSegment[];
  captionChunks: CaptionChunk[];
  scenes: SceneConfig[];
  crossfadeFrames?: number;
}
