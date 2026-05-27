import type { CSSProperties } from "react";
import ColorHash from "color-hash";

const colorHash = new ColorHash({
  saturation: 0.58,
  lightness: [0.42, 0.5, 0.58],
});

export function getAvatarStyle(seed: string | null | undefined): CSSProperties {
  const safeSeed = seed && seed.trim().length > 0 ? seed : "agentpit-user";
  const base = colorHash.hex(safeSeed);
  const accent = colorHash.hex(`${safeSeed}:accent`);

  return {
    backgroundImage: `linear-gradient(135deg, ${base} 0%, ${accent} 100%)`,
    color: "#ffffff",
  };
}
