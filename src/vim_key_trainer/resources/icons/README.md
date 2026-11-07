# 아이콘 원본과 내보내기

내장 imagegen으로 제작한 투명 PNG 원본이다. 팔레트는 앱의 남색 `#10151d`와 연두색 `#c3ef85`에 맞춘다.

- `ok97465.png`: 제목 표시줄·작성자용 OK 원형 마크.
- `vim-key-trainer.png`: Vim·hjkl과 오른쪽 아래 작은 OK 배지를 담은 앱·바탕화면 아이콘.
- 같은 이름의 `.ico`: Windows용 16·20·24·32·40·48·64·128·256px 프레임. 원본 PNG를 교체하면 저장소 루트에서 `uv run python scripts/export_icons.py`로 다시 내보낸다. 추가 이미지 라이브러리는 필요 없다.

제작에 사용한 프롬프트:

## OK 마크

```text
Use case: logo-brand
Asset type: high resolution PNG author logo for a dark desktop application, with a genuinely transparent background.
Primary request: Create a clean, crisp, flat icon based on the attached reference image, which is a solid colored circle with the dark uppercase word OK centered inside. Preserve the reference's simple bold round O and straight diagonal K silhouette.
Input images: the attached teal OK circle is a shape reference, not an edit target. Change its palette to match the app.
Subject: one perfectly round lime-green disc (#c3ef85), with large very bold uppercase dark navy (#10151d) letters "OK" centered as a compact clear monogram. O on left, K on right, even horizontal optical alignment; use broad heavy strokes and clear counters.
Composition: single circle occupying 90% of a square canvas, centered, ample transparent margin, no other shapes.
Text (verbatim): "OK"
Style: precise vector-like geometric flat artwork, clean antialiased edges, professional understated desktop software branding; at least 1024x1024 pixels.
Constraints: only two solid colors, no gradients, no 3D, no shadows, no outer outline, no mockup, no captions, no watermark. True transparent alpha outside the circle. Clearly readable at 16 and 32 pixels.
```

## Vim 연습 아이콘

```text
Use case: logo-brand
Asset type: final high-resolution square transparent PNG application icon for the desktop app "vim-key-trainer".
Primary request: a polished, highly legible Vim keyboard practice icon matching a dark navy and pale lime desktop UI. The application must clearly read as Vim practice. Add the newly created OK circular author badge from the reference at the bottom right, noticeably smaller than the main icon.
Input images: the most recent lime OK circle is the AUTHOR BADGE shape and color reference; use the same simple OK monogram on a lime circle.
Composition: centered large dark navy (#10151d) rounded-square terminal/keycap occupying about 83% of the square. A restrained thin slate border (#425268), generous rounded corners. Inside the upper central area, a large bold crisp pale lime (#c3ef85) word "Vim" (capital V, lowercase i and m) with a small block cursor or underscore on the right. Below it, four separate simple keyboard keys in a single straight row, labeled h j k l, in pale off-white (#e8edf3) on subtly lighter navy (#243041). The four keys evoke repeated keyboard practice. The circular lime badge with the exact bold dark letters "OK" overlaps only the terminal's lower-right corner, badge diameter around 24% of canvas, with a narrow navy separation ring. Keep the badge fully inside the canvas; all main text unobstructed.
Style: premium minimal flat desktop app glyph, precise vector-like shapes and clean antialiasing, strong hierarchy, simple silhouette, suitable at 32/48/256 pixels. High resolution 2048x2048 if possible, square.
Text (verbatim): main "Vim", key labels "h" "j" "k" "l", badge "OK".
Constraints: actual transparent alpha outside the icon; no colored background rectangle; no extra text, no title, no caption, no perspective, no photographic mockup, no watermark, no decorative objects. Avoid excessive gradients, glows, bevels and shadows. Colors limited to dark navy, slate, lime, off-white. All letters accurately formed.
```


## OK 마크 얼룩 제거

```text
Use case: precise-object-edit
Edit target: the provided ok97465.png lime circular OK author logo.
User correction: remove EVERY black smudge, cloud, muddy shadow, texture, and gradient in the green disc. The only dark shapes should be the exact existing "OK" letter strokes.
Change only: replace the entire circular green disc, including the inside of O and every gap between letters, with one perfectly UNIFORM solid flat color #c3ef85 (RGB 195,239,133), 100% opacity inside the circle. Replace the letter strokes with uniform solid #10151d (RGB 16,21,29).
Keep: precisely the existing letter forms and positioning, the same circular silhouette, same canvas proportions.
Clean edge: perfectly smooth, antialiased round silhouette, no stray dots or pixels anywhere outside it. Outside the circle must be genuinely completely transparent (alpha 0), not black. This is a FLAT two-color vector-style raster logo. No illumination, no reflections, no shading, no noise, no paper texture, no shadows, no glow, no gradients, no variation across the disc. No dark spot above OK. Preserve high resolution at least 1254x1254.
Text (verbatim): "OK".
```

