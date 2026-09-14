// The shared shape every brand must provide. Compositions read only from this
// interface, so any brand added here works in every graphic automatically.
export type BrandColors = {
  bg: string; // full-frame background
  panel: string; // raised surface / card
  text: string; // primary text
  textMuted: string; // secondary text
  accent: string; // the one brand accent
  accentSoft: string; // softer variant of the accent
};

export type BrandFonts = {
  display: string; // headlines
  body: string; // labels / body
};

export type Brand = {
  id: string;
  name: string;
  fonts: BrandFonts;
  colors: BrandColors;
};
