# RT Link Logo

## 设计

红色、蓝色鼓面对应太鼓的两种击打音符；中央相扣的链环表达账号连接与成绩同步。白色鼓面边框用于区分两种颜色。采用无文字图形，供插件图标与 README 展示使用。

## 文件

- 插件图标：`../logo.png`
- 格式：PNG，1254 × 1254，RGBA，透明背景；白色圆环属于图案本身。
- 制作方式：内置 image_gen 生成并精修，保留生成文件原始像素与透明通道。
- 本次只新增图标资源与文档，插件版本保持 v0.22.0。

## 初始提示词

```text
Use case: logo-brand
Asset type: finished square logo for the AstrBot plugin RT Link, a Taiko rhythm-game score, rating, and account-linking companion.
Primary request: Design one polished original logomark that fuses two Taiko drumhead/note shapes with an interlocking chain. The red and blue elements should read as a single confident connected emblem, with clean over-under negative-space breaks. Convey rhythm and connection through the geometry itself.
Style/medium: precise flat vector-style graphic rendered as a PNG, bold rounded geometry, beautifully balanced curves, professional app-brand quality, energetic and friendly.
Color palette: the warm vermilion red and clear cyan-blue of Taiko's two note types; flat solid colors.
Composition/framing: one centered symbol on a square canvas, roughly 75 percent of the canvas width, optical balance, comfortable margin, excellent readability at small avatar sizes. Circular drum-like loops rather than a generic elongated chain; a distinctive compact silhouette.
Scene/backdrop: genuine transparent background, transparent cutouts, no background tile.
Constraints: symbol only, no words, no letters, no numbers, no mascot face, no drumsticks, no separate decorative objects, no presentation board, no mockup, no gradients, no bevels, no shadows, no glow, no texture, no watermark. Deliver exactly one final logo.
```

## 精修提示词

以上一轮生成图为编辑目标：

```text
Use case: logo-brand
Asset type: final production PNG logo for RT Link.
Input image: the supplied red-and-blue connected drum logo is the edit target.
Primary request: Refine this exact logo for small app-icon use. Preserve its two colored circular drumheads, white drumhead rings, and distinctive central red/blue interlocking ribbon geometry. Preserve the red drum at upper left and blue drum at lower right and their relative proportions. Perform a clean graphic production pass: make all shapes precisely crisp, smooth and flat-colored; remove the subtle gradients, noisy edge fringes, and any isolated pixels. Retain opaque white rings as part of the mark. Center the complete mark optically on a square canvas and scale it to about 74 percent of canvas width so there is generous transparent padding on every side.
Style: minimal polished vector-style raster logo, three solid fills (vermilion red, cyan blue, white), smoothly antialiased boundaries, no lighting or texture.
Constraints: keep the same design and composition within the mark; no redesign, no added shapes, no letters or text, no watermark, no drop shadow, no background tile. Preserve genuinely transparent background outside the mark. One logo only.
```
