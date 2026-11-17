# RT Link Logo

## 设计

以咚酱、咔酱双鼓击掌为主体：红色鼓面配青色鼓身、青色鼓面配红色鼓身，保留白色鼓缘、圆眼笑脸与短小四肢。击掌表现 Link 的连接含义，鼓棒和红蓝音符强化太鼓节奏游戏的辨识度。

采用粗黑描边、暖白外框、鲜艳红蓝配色与圆润的 `RT LINK` 字标，整体接近日式街机角色徽标风格。

## 文件与参考

- 插件图标：`../logo.png`
- 格式：PNG，1254 × 1254，RGBA，透明背景；暖白描边属于图案本身。
- 制作方式：内置 image_gen，依据角色参考重新生成后精修；保留生成文件原始像素与透明通道。
- 角色参考：[《太鼓达人》官方角色介绍](https://taiko-ch.net/chara/)；[参考图](https://taiko-ch.net/images/chara/donkatsu/img_birth.jpg)采用底部的咚酱、咔酱造型。
- 插件版本保持 v0.22.0。

## 生成提示词

参考图仅用于角色造型，未将原图的图解或文字放入 Logo。

```text
Use case: logo-brand
Asset type: a finished square transparent PNG logo for the AstrBot Taiko score companion plugin "RT LINK".
Input image: official Taiko no Tatsujin character reference ONLY. The reference is a diagram: use ONLY the two finished characters in its BOTTOM panel as character-design references. Do not reproduce the diagram, text, blank drums, spirit shapes, or layout.

Primary request: Create a new lively Taiko no Tatsujin-style mascot logo. The user rejected the earlier abstract chain logo because it did not feel like Taiko no Tatsujin. Make the Taiko characters and arcade rhythm-game identity immediately recognizable.

Main subjects: Don-chan and Katsu-chan as a joyful close-knit duo. Preserve their recognizable designs from the bottom of the reference: Don-chan has a vermilion red/orange circular face and turquoise cylindrical drum body; Katsu-chan has a turquoise-blue circular face and red/orange cylindrical drum body. Both have thick cream-white drumhead rims, simple black dot eyes, wide happy open mouths, and small cream-white arms and feet. Their short cylindrical drum bodies must visibly have depth; do not reduce them to flat circles. Draw the two leaning together in an energetic dancing pose, with their inner hands touching in a friendly high-five to express "Link". Keep both faces unobstructed and large.

Supporting details: a pair of light wooden bachi drumsticks angled behind the duo, plus a very short curved rhythm lane containing just three small alternating red and blue round Taiko notes. These are supporting accents, much smaller than the characters. Avoid a dominant chain emblem.
Typography: directly below the duo, integrate the exact text "RT LINK", spelled R T [space] L I N K, in chunky rounded Japanese-arcade-inspired Latin lettering. Warm cream lettering with a thick near-black outline and restrained red/blue color accents. Large clear letters and playful rhythmic shape; no other writing. The wordmark must belong to the compact logo silhouette, not float far below.
Style/medium: polished 2D Japanese arcade-game mascot illustration; playful festival energy; bold near-black contour lines; clean flat colors; confident hand-drawn-looking curves with crisp edges. Friendly and cheerful, unmistakably Taiko game art, not corporate, metallic, realistic, 3D, or minimalist tech branding.
Palette: vermilion, turquoise/cyan, warm cream, near-black, light wood ochre.
Composition: ONE compact, optically centered emblem on a square canvas; the duo dominates about the upper two-thirds of the mark, wordmark fits directly underneath; all artwork including sticks, notes, and keyline stays within a generous 10 percent safe margin. Strong silhouette, readable at plugin-avatar size. A clean cream-white sticker keyline may unify the emblem.
Background: genuinely transparent outside the logo, no colored square, no scenic background.
Avoid: extra characters, extra limbs, human faces, complex ornaments, small explanatory copy, official title lettering, watermark, mockup, presentation board, gradients, drop shadows, photorealism. Deliver one final logo only.
```

## 精修提示词

以上一轮生成的角色版 Logo 为编辑目标：

```text
Use case: logo-brand
Asset type: production-ready transparent PNG plugin logo.
Input image: the supplied RT LINK mascot logo is the EDIT TARGET, not a loose reference.
Primary request: Keep this exact logo design, the joyful red and blue Taiko drum duo, touching inner hands, the two wooden drumsticks, the three red-blue-red rhythm notes, the three yellow impact wedges, the cream sticker outline, and the exact text "RT LINK". Keep each character's face and cylindrical body colors and all letter shapes recognizable and unchanged.
Make ONE production-cleanup pass. Redraw every silhouette and the continuous cream outer keyline with perfectly clean smooth edges. Eliminate ALL isolated white flecks, dots, residue, torn-paper texture, fuzzy halos, random colored pixels, tiny scratches, and debris that currently surround the outer boundary. The empty space outside the intentional cream keyline must be truly empty transparent pixels. Remove all soft shading and paper texture: use crisp flat solid fills with deliberate clean antialiasing only along intended curves.
Composition: preserve the internal composition but scale the whole cleaned emblem down to 78 percent of the square canvas width and center it, leaving at least 10 percent completely clear transparent padding on every side. Nothing touches or clips against the image edges.
Constraints: genuinely transparent background, preserve alpha; no solid or checkerboard background; no new motifs or text; no gradients, shadows, glow, blur, distressing, mockup, watermark, or redesign. One logo only.
```
