export const FPS = 25;
export const WIDTH = 1080;
export const HEIGHT = 1920;
export const TOP_HEIGHT = 960;
export const BOTTOM_HEIGHT = 960;

export const COLORS = {
  darkBg: '#080808',
  lightBg: '#EAEAEA',
  white: '#FFFFFF',
  accent: '#B0FF00',
  acidGreen: '#B0FF00',
  green: '#B0FF00',
  red: '#E8445A',
  amber: '#FFB800',
  divider: 'rgba(255, 255, 255, 0.25)',
};

export const secToFrame = (sec: number) => Math.round(sec * FPS);

export const FONT = {
  family: '"Inter", system-ui, sans-serif',
  headline: { fontSize: 58, fontWeight: 800 as const, letterSpacing: '-0.03em', lineHeight: 1.18 },
  body: { fontSize: 42, fontWeight: 600 as const, letterSpacing: '-0.01em', lineHeight: 1.3 },
  label: { fontSize: 28, fontWeight: 700 as const, letterSpacing: '0.05em', lineHeight: 1.4 },
};
